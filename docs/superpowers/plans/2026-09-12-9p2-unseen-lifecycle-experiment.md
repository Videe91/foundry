# 9P2 Unseen Lifecycle Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and locally verify the sealed three-arm 9P2 unseen-lifecycle experiment harness, including Kestrel evidence, the old-9P ablation, mechanical root/authority handling, the five-key contrastive leakage gate, fail-fast interleaved execution, immutable artifact capture, and a final pre-run seal — without making any live provider/model/judge call.

**Architecture:** Keep the frozen 9P2 core at `1f89fc86cda463da676bf45603b86a7dcb458452` untouched. Put all new benchmark logic in a new `foundry.experiments.contrastive_unseen` package plus two scripts. Arm F uses the frozen production 9P2 assimilation path; Arm A uses an experiment-only projection of the historical 9P request shape; Arm R uses a fresh governor at every T and the frozen production 9P2 path over cumulative raw evidence. The three arms run in the preregistered rotated order under one global call/cost/authority budget. Semantic grading remains post-run architect work; the harness may only compute structural/integrity facts.

**Tech Stack:** Python 3.12, Pydantic v2 frozen models, existing event-sourced semantic governor, existing xAI semantic adapters, standard library JSON/hashlib/AST/subprocess/pathlib, pytest, ruff, mypy. All implementation tests use scripted/fake reasoners and blocked sockets.

**Spec:** `docs/superpowers/specs/2026-09-12-9p2-unseen-lifecycle-experiment-design.md`

**Approved spec commit:** `099c7e0940056f3ef909d63501f4c12853f4cf13`

**Frozen 9P2 core:** `1f89fc86cda463da676bf45603b86a7dcb458452`

**Experiment version:** `intent-v2-contrastive-unseen-lifecycle-v1`

## Global Constraints

1. `FOUNDRY_CONSTITUTION.md`, `AGENTS.md`, the approved 9P2 design, the pre-experiment amendment, and the approved unseen-lifecycle spec outrank this plan.
2. **ZERO live provider/model/judge calls are authorized by this implementation plan.** Never construct a real xAI reasoner in a test. The final live invocation remains a separate architect gate after the final seal is independently verified.
3. Do not modify any file under:
   - `src/foundry/domain/`
   - `src/foundry/application/`
   - `src/foundry/ports/`
   - `src/foundry/adapters/`
   - `src/foundry/experiments/longitudinal/`
   - `docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/`
4. New runtime experiment code belongs only under `src/foundry/experiments/contrastive_unseen/`.
5. Historical 9P identity remains exactly:
   - policy `intent-v2-9p-v4`
   - prompt SHA `24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1`
   - model-facing schema SHA `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`
6. 9P2 identity remains exactly:
   - policy `intent-v2-9p2-v1`
   - prompt SHA `a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410`
   - same model-facing schema SHA `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`
7. Model/effort are `grok-4.6` / `high`; no tools, search, retry, hidden judge, repair call, or third frontier call.
8. Successful arm/T execution is exactly two frontier calls. Completed experiment = exactly 24 calls.
9. Locked ceilings: 24 frontier calls, 0 judge calls, 16 human authorizations, `$8.00` cumulative provider-reported cost.
10. Kestrel evidence bytes, ids, metadata, lineage, ordering, answer key, error rubric, arm schedule, economics threshold, decision rule, and leakage needles are scientific design. Do not change them during implementation.
11. The experiment may deterministically record structural facts only. It may not decide semantic equivalence, whether a claim matches the hidden answer key, whether two addresses represent one locus, or whether a pre-change subclaim is materially compatible. Those remain architect adjudication after raw artifacts are frozen.
12. Arm A is an experiment-only ablation. Do not change frozen production assembly functions to make it work.
13. Arm F and R use the real frozen `assimilate_delta` path. Do not fork or modify 9P2 core behavior.
14. Historical comparison material remains non-citable. The harness must prove every proposal evidence reference is a subset of that exact request's `ReasoningRequest.evidence`.
15. Strict TDD for every implementation task: write intended behavioral test -> run RED for the expected reason -> minimum GREEN -> targeted verification -> task review -> commit.
16. Provider-adjacent tests must block sockets. No environment containing an API key is necessary for implementation verification.
17. Any Critical/Important code-review finding must be resolved with a new RED/GREEN cycle before continuing.
18. No experiment evidence or hidden-answer text may be copied into prompts, model task guidance, address/claim fixtures used by the leakage skeleton, or runtime semantic helpers.
19. Pre-run `manifest.json` and `expectations.json` are created only after harness code is green. The final seal commit adds only those two files.
20. The final allowed implementation conclusion is: **`9P2 unseen-lifecycle harness locally verified and sealed; live experiment remains unauthorized pending architect verification.`**

---

## File Map

New package:

- `src/foundry/experiments/contrastive_unseen/__init__.py`
- `src/foundry/experiments/contrastive_unseen/timeline.py`
- `src/foundry/experiments/contrastive_unseen/expectations.py`
- `src/foundry/experiments/contrastive_unseen/designation.py`
- `src/foundry/experiments/contrastive_unseen/authority.py`
- `src/foundry/experiments/contrastive_unseen/ablation.py`
- `src/foundry/experiments/contrastive_unseen/records.py`
- `src/foundry/experiments/contrastive_unseen/leakage.py`
- `src/foundry/experiments/contrastive_unseen/integrity.py`
- `src/foundry/experiments/contrastive_unseen/runner.py`
- `src/foundry/experiments/contrastive_unseen/artifacts.py`

New scripts:

- `scripts/prepare_contrastive_unseen_lifecycle.py`
- `scripts/run_contrastive_unseen_lifecycle.py`

New tests:

- `tests/unit/test_contrastive_unseen_timeline.py`
- `tests/unit/test_contrastive_unseen_expectations.py`
- `tests/unit/test_contrastive_unseen_designation.py`
- `tests/unit/test_contrastive_unseen_authority.py`
- `tests/unit/test_contrastive_unseen_ablation.py`
- `tests/unit/test_contrastive_unseen_leakage.py`
- `tests/unit/test_contrastive_unseen_integrity.py`
- `tests/unit/test_contrastive_unseen_records.py`
- `tests/unit/test_contrastive_unseen_runner.py`
- `tests/unit/test_contrastive_unseen_artifacts.py`
- `tests/integration/test_contrastive_unseen_entrypoint.py`

Pre-run sealed artifacts, created only in T8:

- `docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/manifest.json`
- `docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/expectations.json`

---

## T0 — Isolated workspace and baseline

No code change and no commit.

- [ ] Verify branch contains approved spec commit `099c7e0940056f3ef909d63501f4c12853f4cf13`.
- [ ] Use `superpowers:using-git-worktrees` for a dedicated isolated worktree.
- [ ] Initialize the SDD ledger for this exact plan.
- [ ] Read in full:
  - `FOUNDRY_CONSTITUTION.md`
  - `AGENTS.md`
  - `docs/superpowers/specs/2026-09-12-contrastive-semantic-assimilation-design.md`
  - `docs/superpowers/specs/2026-09-12-9p2-pre-experiment-amendment.md`
  - `docs/superpowers/specs/2026-09-12-9p2-unseen-lifecycle-experiment-design.md`
  - this plan.
- [ ] Confirm clean starting state:

```bash
git rev-parse HEAD
git status --short
git merge-base --is-ancestor 1f89fc86cda463da676bf45603b86a7dcb458452 HEAD
```

Expected HEAD at plan start is the commit containing this plan; status empty; frozen core is an ancestor.

- [ ] Baseline focused suite:

```bash
uv run pytest -q \
  tests/unit/test_9p2_track_a_regression.py \
  tests/unit/test_contrastive_context.py \
  tests/unit/test_incremental_assimilation.py \
  tests/unit/test_xai_lifecycle_prompt.py \
  tests/unit/test_xai_lifecycle_drafts.py \
  tests/unit/test_xai_semantic_reasoner.py \
  tests/unit/test_xai_pair_contract.py \
  tests/unit/test_xai_decimal_contract.py
```

Expected PASS. A baseline failure is not experiment implementation work; use systematic debugging and stop until understood.

---

## T1 — Frozen Kestrel timeline and scientific decision contract

**Commit:** `experiment: define 9P2 unseen lifecycle contract`

### Files

- NEW `src/foundry/experiments/contrastive_unseen/__init__.py`
- NEW `src/foundry/experiments/contrastive_unseen/timeline.py`
- NEW `src/foundry/experiments/contrastive_unseen/expectations.py`
- NEW `tests/unit/test_contrastive_unseen_timeline.py`
- NEW `tests/unit/test_contrastive_unseen_expectations.py`

### Timeline contract

`timeline.py` owns only model-visible evidence and deterministic schedule data. It must not import `expectations.py`.

Lock these constants:

```python
EXPERIMENT_VERSION = "intent-v2-contrastive-unseen-lifecycle-v1"
PROJECT_ID = "PROJ-9P2-UNSEEN-KESTREL"
SCOPE = "kestrel-delivery"
SCOPE_TUPLE = (SCOPE,)
FROZEN_CORE_SHA = "1f89fc86cda463da676bf45603b86a7dcb458452"
ARM_SCHEDULE = (
    (1, "F"), (1, "A"), (1, "R"),
    (2, "A"), (2, "R"), (2, "F"),
    (3, "R"), (3, "F"), (3, "A"),
    (4, "F"), (4, "A"), (4, "R"),
)
MAX_FRONTIER_CALLS = 24
MAX_JUDGE_CALLS = 0
MAX_HUMAN_AUTHORIZATIONS = 16
MAX_COST_USD = 8.0
```

Define a frozen experiment-only `LifecycleEvidence` with exactly:

```python
class LifecycleEvidence(FrozenModel):
    t: int = Field(ge=1, le=4)
    item: EvidenceItem
```

Build `TIMELINE` at import time with `evidence_item(...)` and the exact evidence bytes/metadata from approved spec §5. No files, git history, environment variables, or current time may influence the evidence.

The exact observed timestamps are:

- A1 `2026-09-01T00:00:00Z`
- B1 `2026-09-01T00:01:00Z`
- N1 `2026-09-01T00:02:00Z`
- A2 `2026-09-02T00:00:00Z`
- A3 `2026-09-03T00:00:00Z`
- B2 `2026-09-04T00:00:00Z`

Exports:

```python
persistent_delta(t: int, *, project_id: str) -> tuple[EvidenceItem, ...]
reconstruction_corpus(t: int, *, project_id: str) -> tuple[EvidenceItem, ...]
evidence_records() -> tuple[dict[str, object], ...]
```

`persistent_delta` returns exactly T1 `(A1,B1,N1)`, T2 `(A2,)`, T3 `(A3,)`, T4 `(B2,)`, with only `project_id` replaced. `reconstruction_corpus` returns every version `<= t` in frozen timeline order, again replacing only `project_id`.

`evidence_records()` records `t`, evidence id, source kind, source ref, artifact ref, supersedes id, ISO timestamp, scope, content SHA256, and content byte length. It does not duplicate hidden answer-key semantics.

### Scientific contract

`expectations.py` is grading/preflight data and MUST NOT be imported by `timeline.py`, `ablation.py`, `records.py`, or `runner.py`.

Lock:

```python
GRADING_LABELS = (
    "C1", "C2", "C3",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8",
    "F_SEMANTIC", "CAUSAL", "ECONOMY", "NO_WORSE_R", "INTEGRITY",
)
```

Lock the full answer-key sentences and normalized conclusions exactly from approved spec §§6, 10, 14.5. Do not paraphrase them in code.

Define:

```python
class IntegrityInputs(FrozenModel):
    f1: bool
    f2: bool
    f3: bool
    f4: bool
    f5: bool
    f6: bool
    f7: bool
    f8: bool

class DecisionInputs(FrozenModel):
    f_material_errors: int = Field(ge=0, le=3)
    a_material_errors: int = Field(ge=0, le=3)
    r_material_errors: int = Field(ge=0, le=3)
    f_input_tokens_t2_t4: int = Field(ge=0)
    r_input_tokens_t2_t4: int = Field(ge=0)
    integrity: IntegrityInputs

class DecisionOutcome(FrozenModel):
    result: Literal["PASS", "INCONCLUSIVE", "FAIL"]
    failing: tuple[str, ...]
    note: str
```

`decision_rule` is exact:

```text
F_SEMANTIC = f_material_errors == 0
CAUSAL     = f_material_errors < a_material_errors
ECONOMY    = 4*f_input_tokens_t2_t4 <= 3*r_input_tokens_t2_t4
NO_WORSE_R = f_material_errors <= r_material_errors
INTEGRITY  = f1..f8 all true

PASS         iff all five are true
INCONCLUSIVE iff F_SEMANTIC and not CAUSAL and ECONOMY and NO_WORSE_R and INTEGRITY
FAIL         otherwise
```

For PASS and INCONCLUSIVE, `failing == ()`. INCONCLUSIVE note is exactly `"CAUSAL_NOT_ESTABLISHED: Arm A was also semantically correct."`. For FAIL, `failing` lists each false component in this order: `F_SEMANTIC`, `CAUSAL`, `ECONOMY`, `NO_WORSE_R`, then false `F1`..`F8`. No threshold is configurable.

Expose a canonical `expectations_document()` containing the approved answer key, C1/C2/C3 rubric, F1-F8 descriptions, decision rule, and leakage needle source material. It is grading data only.

### RED tests

Prove before implementation:

- exact ids/order/metadata/content/lineage for all six evidence items;
- exact persistent deltas and cumulative R corpora;
- content hashes recompute from literal content;
- schedule is exactly the 12-entry rotation above;
- `timeline.py` source does not import `expectations`;
- decision PASS case;
- decision INCONCLUSIVE case when F=A=0;
- each false component produces FAIL and is named;
- 25% economy boundary uses integer inequality exactly (equality passes, one unit beyond fails);
- error counts reject outside 0..3;
- expectations document contains the exact sealed wording but no runtime IDs.

Run RED then GREEN:

```bash
uv run pytest -q tests/unit/test_contrastive_unseen_timeline.py tests/unit/test_contrastive_unseen_expectations.py
uv run ruff check src/foundry/experiments/contrastive_unseen tests/unit/test_contrastive_unseen_timeline.py tests/unit/test_contrastive_unseen_expectations.py
uv run mypy src/foundry/experiments/contrastive_unseen/timeline.py src/foundry/experiments/contrastive_unseen/expectations.py
```

Commit exact message above.

---

## T2 — Mechanical root designation and authority

**Commit:** `experiment: add mechanical Kestrel roots and authority`

### Files

- NEW `src/foundry/experiments/contrastive_unseen/designation.py`
- NEW `src/foundry/experiments/contrastive_unseen/authority.py`
- NEW `tests/unit/test_contrastive_unseen_designation.py`
- NEW `tests/unit/test_contrastive_unseen_authority.py`

### Root designation

Define:

```python
class RootDesignation(FrozenModel):
    key: Literal["A", "B", "N"]
    seed_evidence_id: str
    status: Literal["DESIGNATED", "UNDESIGNATED"]
    address_id: str | None
    claim_ids: tuple[str, ...]
    creating_judgment_ids: tuple[str, ...]
    reason: str
```

`designate_seed_root(state, *, key, seed_evidence_id)`:

1. derive the current semantic view;
2. take live claim ids from `view.effective_evidence` whose effective evidence contains the seed id;
3. sort claim ids;
4. map them to `state.semantic.claims[claim_id].address_id`;
5. if none -> UNDESIGNATED with reason `"NO_LIVE_SEED_SUPPORTED_CLAIM"`;
6. if they span more than one unique address -> UNDESIGNATED with reason `"MULTIPLE_SEED_SUPPORTED_ADDRESSES"`;
7. otherwise return DESIGNATED with that one address, all seed-supported claim ids, and all corresponding `created_by_judgment_id` values sorted/deduplicated.

No claim wording, address descriptors, predicate, value, or semantic similarity may be inspected.

### Authority identity

Lock:

```python
ARCHITECT_ACTOR = "architect"
HUMAN_FINGERPRINT = ReasonerFingerprint(
    provider="human",
    model="human://architect",
    policy_version="intent-v2-9p2-unseen-v1",
)
```

Because `SemanticGovernor.submit` authenticates `human_actor_id` against the human fingerprint's `model`, the authenticated actor passed to `submit` MUST be `"human://architect"`. The experiment artifact separately records logical `actor_id="architect"`. Do not weaken the governor trust boundary to make the display actor string match.

`record_architect_authority` creates one project-wide active canonical `AuthorityRecord` with `authorized_by="human://architect"`, subject `material-semantic-change`, and human provenance. This happens for F and A sessions before T1 and makes no model call.

Define experiment-only outcomes:

```python
class AuthorizationOutcome(StrEnum):
    AGREED = "AGREED"
    NO_PROPOSAL = "NO_PROPOSAL"
    AMBIGUOUS_PROPOSALS = "AMBIGUOUS_PROPOSALS"
    NON_ROOT_NOT_AUTHORIZED = "NON_ROOT_NOT_AUTHORIZED"

class AuthorizationRecord(FrozenModel):
    arm: Literal["F", "A"]
    t: Literal[2, 4]
    root_key: Literal["A", "B"]
    target_judgment_id: str
    outcome: AuthorizationOutcome
    pending_judgment_ids: tuple[str, ...]
    submitted_judgment_id: str | None
    proposal_signature: tuple[str, ...] | None
    actor_id: Literal["architect"] = "architect"
```

`authorize_root_supersessions(...)` receives the governor, designated root, all pending supersede judgment ids from that step, shared authorization counter, and deterministic clock/id factory.

For every root `creating_judgment_id`:

- find pending `SupersedeProposal`s targeting exactly that id;
- zero => NO_PROPOSAL;
- more than one => AMBIGUOUS_PROPOSALS, submit none;
- exactly one => before writing, enforce global counter `<16`, verify a live project-wide authority record exists, construct a human `SemanticJudgment` with the **same proposal object**, empty visible evidence, `rationale=f"AGREE: {pending_id}"`, `HUMAN_FINGERPRINT`, then `governor.submit(..., human_actor_id="human://architect")`; require route APPLY with `HUMAN_AUTHORITY`; increment counter; record AGREED.

Pending supersedes targeting any non-root judgment are never submitted. Record one `NON_ROOT_NOT_AUTHORIZED` entry per such pending id after root-target records, sorted by pending judgment id. They do not consume the authorization counter.

If root is UNDESIGNATED, no proposal is authorized; return no root-target records plus NON_ROOT records for all pending supersedes. This is semantic failure evidence, not operational failure.

If an agreement would exceed 16, raise `AuthorizationCeilingExceeded` before the durable write.

### RED tests

Prove:

- zero claims -> undesignated;
- one address with one claim -> designated;
- one address with multiple seed-supported claims -> designated with all sorted claims/judgments;
- same seed across two addresses -> undesignated;
- designation ignores wording entirely;
- authority record exists before human AGREE;
- exact one root-target supersede is applied with identical `proposal_signature`;
- no-proposal and ambiguous cases submit nothing;
- non-root supersede is never authorized;
- global 16 ceiling refuses the 17th before writing;
- the human judgment fingerprint and authenticated actor satisfy the governor's existing trust boundary;
- no frontier reasoner is called by designation/authority code.

Run:

```bash
uv run pytest -q tests/unit/test_contrastive_unseen_designation.py tests/unit/test_contrastive_unseen_authority.py
uv run ruff check src/foundry/experiments/contrastive_unseen/designation.py src/foundry/experiments/contrastive_unseen/authority.py tests/unit/test_contrastive_unseen_designation.py tests/unit/test_contrastive_unseen_authority.py
uv run mypy src/foundry/experiments/contrastive_unseen/designation.py src/foundry/experiments/contrastive_unseen/authority.py
```

Commit exact message above.

---

## T3 — Experiment-only historical 9P ablation

**Commit:** `experiment: add frozen 9P ablation arm`

### Files

- NEW `src/foundry/experiments/contrastive_unseen/ablation.py`
- NEW `tests/unit/test_contrastive_unseen_ablation.py`

Arm A must reproduce the historical **model-visible treatment**, not call current 9P2 assembly and delete fields afterward.

Exports:

```python
assemble_ablation_call1(*, project_id, delta, state, scope) -> ReasoningRequest
assemble_ablation_call2(*, project_id, delta, state, neighborhood) -> ReasoningRequest
assimilate_ablation_delta(*, governor, reasoner, delta, scope) -> AblationOutcome
```

Call 1:

- ingest delta in order;
- use `active_in_scope_addresses(state, scope)`;
- `known_addresses` = all active in-scope addresses;
- `known_claims = ()`;
- `comparison_context = ComparisonContext()`;
- allowed kinds exactly `ASSIMILATION_JUDGMENT_KINDS` (`BIND_TO_ADDRESS`, `CREATE_ADDRESS`);
- same 200-address refusal rule as historical/current support bound.

After Call 1, derive neighborhood only from applied Call-1 CREATE/BIND decisions using existing `neighborhood_from_decisions`.

Call 2:

- `known_addresses` = exactly neighborhood addresses;
- `known_claims` = `live_claims_at(state, neighborhood)`;
- `comparison_context = ComparisonContext()`;
- no contrastive widening;
- allowed kinds exactly `CLAIM_ASSIMILATION_JUDGMENT_KINDS`.

`assimilate_ablation_delta` calls `governor.propose_and_submit` exactly twice and returns stage decisions, neighborhood, pending supersede ids, and `calls_made=2`. No retry/try-another-path logic.

Arm A's live reasoner later MUST be historical `XAISemanticReasoner`; the ablation module itself constructs no adapter.

### RED tests

Use a request-recording scripted reasoner and real governor. Prove:

- T1 Call 1 sees addresses but zero claims and empty comparison context;
- after prior claims exist, later Call 1 still sees zero claims;
- Call 2 sees only Call-1 decision neighborhood claims;
- structurally touched address not in the decision neighborhood does not widen Call 2;
- `render_request(request, include_comparison_context=False)` has historical four-key shape and contains no `comparison_context` key;
- exactly two calls on success;
- a Call-2 exception propagates, Call-1 state remains, no retry;
- 201 active in-scope addresses refuse before first reasoner call;
- source contains no `XAIContrastiveSemanticReasoner`, no semantic matching, and no import from `expectations`.

Run:

```bash
uv run pytest -q tests/unit/test_contrastive_unseen_ablation.py
uv run ruff check src/foundry/experiments/contrastive_unseen/ablation.py tests/unit/test_contrastive_unseen_ablation.py
uv run mypy src/foundry/experiments/contrastive_unseen/ablation.py
```

Commit exact message above.

---

## T4 — Exact request recording, leakage gate, and preflight integrity

**Commit:** `experiment: add 9P2 unseen preflight and leakage gate`

### Files

- NEW `src/foundry/experiments/contrastive_unseen/records.py`
- NEW `src/foundry/experiments/contrastive_unseen/leakage.py`
- NEW `src/foundry/experiments/contrastive_unseen/integrity.py`
- NEW `tests/unit/test_contrastive_unseen_records.py`
- NEW `tests/unit/test_contrastive_unseen_leakage.py`
- NEW `tests/unit/test_contrastive_unseen_integrity.py`

### Exact request recorder

Define `RequestRecord` with:

```python
arm: Literal["F", "A", "R"]
t: int
call_number: Literal[1, 2]
policy_version: str
system_prompt_sha256: str
rendered_user_request: str
request_sha256: str
citable_evidence_ids: tuple[str, ...]
historical_comparison_evidence_ids: tuple[str, ...]
known_address_ids: tuple[str, ...]
known_claim_ids: tuple[str, ...]
allowed_judgment_kinds: tuple[str, ...]
comparison_context_chars: int
```

A `RecordingReasoner` delegates to an inner `SemanticReasoner` and never changes the request or returned judgments. It is configured per arm with:

- F/R: contrastive policy/hash and `include_comparison_context=True`;
- A: historical policy/hash and `include_comparison_context=False`.

Before each step, caller invokes `begin_step(t)`. `propose()` increments a per-step call number and refuses call 3. It renders the exact user request via frozen `render_request`, hashes UTF-8 bytes, records IDs directly from the `ReasoningRequest`, uses `historical_evidence_ids(request.comparison_context)`, and uses `comparison_context_character_count` for F/R; A must record `0` because its context is empty and omitted from rendering.

The recorder must support scripted reasoners without receipts during tests. Live receipt/cost accounting is added in T5, not guessed here.

### Leakage gate

`leakage.py` may import `expectations.py`; provider/request-path modules may not.

Normalization is exactly:

```python
" ".join(text.casefold().split(" "))
```

implemented so only consecutive ASCII space characters collapse; tabs/newlines first map to a single ASCII space, then repeated spaces collapse. Do not perform Unicode normalization, stemming, fuzzy matching, punctuation removal, or semantic matching.

Needles include exactly:

- every `GRADING_LABELS` item as a word-bounded label;
- every full hidden answer-key sentence in `expectations_document()`;
- the four normalized conclusions from approved spec §14.5;
- no actual evidence text.

Expose `needle_set_sha256()` over canonical sorted needle strings.

Build deterministic synthetic skeletons with opaque values only. Use real `EvidenceItem`, real governor/assembly paths, and real request rendering. Skeleton semantic strings use values like `SUBJECT_ALPHA`, `FACET_ALPHA`, `CLAIM_VALUE_ALPHA`, never Kestrel/answer wording.

Required skeleton ids:

- `F_T1_CALL1_NO_PREDECESSOR`
- `F_CORRECTION_CALL1_TOUCHED`
- `F_CORRECTION_CALL2_TOUCHED`
- `F_RESTATEMENT_CALL1_TOUCHED`
- `F_RESTATEMENT_CALL2_TOUCHED`
- `A_CALL1_NO_CLAIMS`
- `A_CALL2_WITH_CLAIMS_NO_CONTEXT`
- `R_CUMULATIVE_CALL1`
- `R_CUMULATIVE_CALL2`

F/R render with `CONTRASTIVE_SYSTEM_INSTRUCTION` + five-key request, A with `SYSTEM_INSTRUCTION` + historical four-key request. Placeholder evidence bytes are used to generate real lineage diffs. Actual hidden answer/evidence semantics are never inserted.

`LeakageResult` records needle-set SHA, each skeleton SHA, prompt hashes, PASS/FAIL, and exact offending needle/skeleton when failed.

Tests must mutation-prove the gate: inserting each representative hidden phrase into static harness text makes it fail; placing the same phrase in excluded evidence placeholder input does not count as harness leakage.

### Preflight

`integrity.py` defines injected protocols for Git and command execution; it never shells out itself and never constructs a provider client.

The exact 20 scientific preflight gates from approved spec §15 are emitted in fixed order with stable names. Use these names:

1. `head_equals_final_seal`
2. `worktree_clean`
3. `seal_descends_from_frozen_core`
4. `core_paths_unchanged_since_frozen_core`
5. `fr_policy_is_9p2`
6. `fr_prompt_hash_frozen`
7. `a_policy_is_9p`
8. `a_prompt_hash_frozen`
9. `output_schema_hash_frozen`
10. `f_calls_per_delta_is_2`
11. `a_two_calls_no_retry`
12. `r_uses_fresh_ledger_per_t`
13. `evidence_manifest_frozen`
14. `arm_schedule_frozen`
15. `ceilings_frozen`
16. `answer_key_not_imported_by_request_path`
17. `contrastive_leakage_gate_passes`
18. `track_a_regression_passes`
19. `scope_closure_regression_passes`
20. `historical_9p_artifacts_unchanged`

Gate 4 rejects any diff path from frozen core under `src/foundry/domain/`, `application/`, `ports/`, or `adapters/`. Experiment code under `src/foundry/experiments/contrastive_unseen/`, scripts, tests, plans/specs, and this experiment directory is allowed.

Gate 16 statically parses imports with `ast` in these model/request-path modules:

- `timeline.py`
- `designation.py`
- `authority.py`
- `ablation.py`
- `records.py`
- `runner.py` once it exists

None may import `.expectations`, the full expectations module path, or call a grading helper. `leakage.py`, `integrity.py`, `artifacts.py`, and seal-preparation code may import grading data because they never enter the provider request path.

Gates 18 and 19 execute fresh local pytest commands through injected command runner:

```bash
uv run pytest -q tests/unit/test_9p2_track_a_regression.py
uv run pytest -q tests/unit/test_incremental_assimilation.py -k 'shared_predecessor_never_widens_call_two_into_another_scope or project_wide_address_remains_eligible_for_a_scoped_delta'
```

No network reachability gate.

### RED/GREEN

```bash
uv run pytest -q \
  tests/unit/test_contrastive_unseen_records.py \
  tests/unit/test_contrastive_unseen_leakage.py \
  tests/unit/test_contrastive_unseen_integrity.py
uv run ruff check src/foundry/experiments/contrastive_unseen tests/unit/test_contrastive_unseen_records.py tests/unit/test_contrastive_unseen_leakage.py tests/unit/test_contrastive_unseen_integrity.py
uv run mypy src/foundry/experiments/contrastive_unseen/records.py src/foundry/experiments/contrastive_unseen/leakage.py src/foundry/experiments/contrastive_unseen/integrity.py
```

Commit exact message above.

---

## T5 — Interleaved three-arm runner and global fail-fast budgets

**Commit:** `experiment: add interleaved three-arm runner`

### Files

- NEW `src/foundry/experiments/contrastive_unseen/runner.py`
- NEW `tests/unit/test_contrastive_unseen_runner.py`

### Runner status

Define:

```python
class RunStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    ABORTED_PREFLIGHT = "ABORTED_PREFLIGHT"
    ABORTED_PROVIDER = "ABORTED_PROVIDER"
    ABORTED_MODEL_CONTRACT = "ABORTED_MODEL_CONTRACT"
    ABORTED_RUNTIME = "ABORTED_RUNTIME"
    ABORTED_AUTHORITY_CEILING = "ABORTED_AUTHORITY_CEILING"
    ABORTED_BUDGET = "ABORTED_BUDGET"
    COMPLETED = "COMPLETED"
```

Runner receives already-constructed reasoners so tests can use fakes. CLI construction occurs only in T7 after preflight passes.

Create one persistent F session and one persistent A session, each with:

- its own `InMemoryEventStore`;
- its own `SemanticGovernor` and stable project id (`PROJ-9P2-F`, `PROJ-9P2-A`);
- one project-wide architect authority record written before T1;
- own root-designation map;
- own `RecordingReasoner`.

Each R schedule entry creates a **fresh** store/governor/project id `PROJ-9P2-R-T{t}` and receives cumulative corpus through T. R never has an authority record and state is discarded after its record is captured.

F uses real `assimilate_delta`; A uses `assimilate_ablation_delta`; R uses real `assimilate_delta`.

### Frozen interleaving

Iterate exactly `ARM_SCHEDULE`. Do not call `run_arm_f` or `run_arm_r`, because they group arms rather than interleave them.

After F/A T1, mechanically designate A/B/N roots from that arm's own state.

After F/A T2 Call 2, call mechanical authority for A root. After F/A T4, call it for B root. No authority step at T3. Root/authority behavior never reads hidden answer-key semantics.

### Global frontier/cost budget

Define one shared `ExperimentBudget` with:

```python
frontier_calls: int
provider_cost_usd: Decimal
human_authorizations: int
```

`BudgetedReasoner` wraps each `RecordingReasoner` and shares the budget object.

Before forwarding any request:

- if `frontier_calls >= 24`, raise `ExperimentBudgetExceeded` before the call;
- increment `frontier_calls` exactly when the request is actually forwarded.

Around `inner.propose(request)` snapshot the underlying adapter receipts when available. In `finally`, account every newly appended receipt exactly once. For live xAI adapters a successful/structurally-failed provider call must append at most one new receipt; if more than one appears for one propose call, raise runtime integrity failure. Scripted tests may expose no receipts.

After accounting a receipt, if cumulative provider cost is `> Decimal("8.0")`, raise `ExperimentBudgetExceeded` **after recording that spent call** and before any later call. Returned model judgments from the budget-breaching call are not forwarded to governance because the wrapper raises before returning them.

Human authorization increments the same shared counter only for successful AGREED submissions; the authority module refuses a write that would exceed 16.

### Fail-fast classification

The top-level runner catches once around each scheduled arm/T operation. On first operational exception:

- `XAIProviderError` -> `ABORTED_PROVIDER`
- `SemanticOutputError` -> `ABORTED_MODEL_CONTRACT`
- `AuthorizationCeilingExceeded` -> `ABORTED_AUTHORITY_CEILING`
- `ExperimentBudgetExceeded` -> `ABORTED_BUDGET`
- all other operational exceptions, including `ContextUnsupported`, identity guard errors, and unexpected runtime errors -> `ABORTED_RUNTIME`
- `KeyboardInterrupt` -> `ABORTED_RUNTIME` with error `INTERRUPTED: KeyboardInterrupt`
- never catch `SystemExit`.

After abort, do not call another arm/T. Create structural NOT_RUN schedule entries for all remaining schedule positions. Never retry the failed call or T.

A semantically bad but structurally valid response is not an exception and does not stop the run.

### Step/result records

Capture enough raw state for later artifacts and adjudication:

- arm/T/status/error;
- evidence ids shown;
- two request records;
- admission decisions from both stages;
- pending supersede ids;
- root designations after T1;
- authority records;
- state/view snapshots after the step;
- ledger snapshot;
- receipts/draft payloads since prior step when exposed.

For F final result also compute replay equality against its final state/view using existing replay machinery or read-only `longitudinal.scoring.replay_matches`; do not modify historical code.

No semantic checkpoint is graded here.

### RED tests

With fake/scripted reasoners and blocked sockets prove:

- successful run follows exact 12-position schedule and 24 calls;
- F/A states persist while each R T starts with independent sequence 1 / fresh store;
- F uses current 9P2 path and A uses ablation path;
- T1 roots are designated mechanically for F/A;
- authority executes only after persistent T2/T4;
- failure at any arm/T marks all later schedule positions NOT_RUN and no more reasoner calls happen;
- provider/model-contract/budget/authority/runtime statuses classify correctly;
- 25th call is refused before forwarding;
- a call pushing cost above $8 is recorded/accounted then stops later calls;
- semantic wrongness by itself does not abort;
- no `expectations` import in runner;
- no third call/retry/fallback exists.

Run:

```bash
uv run pytest -q tests/unit/test_contrastive_unseen_runner.py
uv run ruff check src/foundry/experiments/contrastive_unseen/runner.py tests/unit/test_contrastive_unseen_runner.py
uv run mypy src/foundry/experiments/contrastive_unseen/runner.py
```

Commit exact message above.

---

## T6 — Sealed preregistration and raw artifact writers

**Commit:** `experiment: add sealed unseen lifecycle artifacts`

### Files

- NEW `src/foundry/experiments/contrastive_unseen/artifacts.py`
- NEW `scripts/prepare_contrastive_unseen_lifecycle.py`
- NEW `tests/unit/test_contrastive_unseen_artifacts.py`

### Canonical JSON

Use canonical sealing bytes:

```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

Pretty on-disk JSON may use `indent=2, sort_keys=True, ensure_ascii=False` plus final newline; seal hashes are over canonical parsed data, not pretty bytes.

### Manifest

Define typed `ExperimentManifest`. It contains at minimum:

- experiment version;
- artifact format version `1`;
- frozen core SHA;
- `harness_code_sha` = clean HEAD **before** preregistration files are written;
- `final_seal_rule` string: `"live HEAD must equal --frozen-sha; its single parent must equal harness_code_sha; parent..HEAD may add only manifest.json and expectations.json"`;
- approved spec path and SHA256 of exact spec bytes;
- provider/model/effort;
- F/R policy + prompt SHA;
- A policy + prompt SHA;
- output schema SHA;
- arm schedule;
- four ceilings;
- exact evidence records from T1;
- economy inequality text `4*F_input_tokens_T2_T4 <= 3*R_input_tokens_T2_T4`;
- decision-result set PASS/INCONCLUSIVE/FAIL;
- leakage needle-set SHA;
- canonical `expectations_sha256`;
- historical 9P artifact directory path.

No self-referential final seal SHA is embedded.

`expectations.json` is exactly canonical data returned by `expectations_document()` and includes the answer key/rubric/decision rule. It is never imported by model request path.

### Prepare script

`prepare_contrastive_unseen_lifecycle.py`:

- requires clean worktree;
- requires current HEAD descends from frozen core;
- takes `--out` with default exactly `docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1`;
- refuses if either `manifest.json` or `expectations.json` already exists;
- computes spec SHA from working-tree bytes which must equal `git show HEAD:<spec path>` bytes;
- sets `harness_code_sha` to current HEAD;
- writes exactly the two prereg files and prints their canonical hashes;
- constructs no reasoner and performs no network access.

### Raw artifact writer

Implement write-once helpers for later T7:

- `preflight.json`
- `verdicts.json`
- `report.md`
- F/A request/draft/receipt/decision/authorization/ledger/result files
- R/T1..T4 request/draft/receipt/decision/ledger/result files.

Refuse overwrite of any raw live artifact path. If a preflight file already exists, live entrypoint refuses to start under that seal; a failed preflight must be preserved and later handling returns to architect rather than silently replacing it.

Raw `verdicts.json` after a COMPLETED run contains deterministic F1/F3/F4/F5/F6/F7/F8 where computable, architect fields `null` for F2 and semantic C1/C2/C3 across F/A/R, material-error totals `null`, and scientific decision `null`. It must not guess semantic verdicts.

For an operational abort, verdict/report explicitly say `scientific_decision = null`.

### Secret hygiene

No API key/auth value is accepted by artifact APIs. Before writing, recursively scan strings for secret-shaped tokens equivalent to existing xAI artifact hygiene (`api_key`, authorization/bearer material, `xai-...`). Error text may be sanitized to `<redacted-secret>`; exact rendered user request must be secret-free by construction and causes artifact writing to fail if a secret pattern appears there.

### RED tests

Prove:

- manifest canonical hash stable across mapping insertion order;
- expectations hash matches exact canonical expectations document;
- prepare refuses dirty tree and existing files;
- prepare writes exactly two files;
- `harness_code_sha` is pre-artifact HEAD;
- raw writers create exact directory contract;
- overwrite refusal;
- requests preserve exact rendered text/hash;
- secret patterns never persist;
- raw verdicts contain no invented semantic decisions;
- no previous 9P artifact path is touched.

Run:

```bash
uv run pytest -q tests/unit/test_contrastive_unseen_artifacts.py
uv run ruff check src/foundry/experiments/contrastive_unseen/artifacts.py scripts/prepare_contrastive_unseen_lifecycle.py tests/unit/test_contrastive_unseen_artifacts.py
uv run mypy src/foundry/experiments/contrastive_unseen/artifacts.py
```

Commit exact message above.

---

## T7 — Live entrypoint with preflight-before-construction law

**Commit:** `experiment: add unseen lifecycle entry point`

### Files

- NEW `scripts/run_contrastive_unseen_lifecycle.py`
- NEW `tests/integration/test_contrastive_unseen_entrypoint.py`

### CLI modes

Mutually exclusive:

```text
--preflight-only
--live
```

Required common args:

```text
--frozen-sha <40 hex>
--out docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1
```

`--preflight-only`:

- evaluates all gates against sealed files and supplied SHA;
- prints full preflight JSON to stdout;
- does not write `preflight.json`;
- does not read `XAI_API_KEY`;
- does not construct any reasoner/client;
- exits nonzero if any gate fails.

`--live`:

1. require sealed manifest/expectations to exist;
2. require no existing `preflight.json` or raw-run artifact;
3. evaluate all preflight gates **before reading API key or constructing reasoners**;
4. write `preflight.json` exactly once;
5. if any gate failed: exit with `ABORTED_PREFLIGHT`, zero calls;
6. only then read `XAI_API_KEY`;
7. construct:
   - F `XAIContrastiveSemanticReasoner(model="grok-4.6", reasoning_effort="high")`
   - A `XAISemanticReasoner(model="grok-4.6", reasoning_effort="high")`
   - R `XAIContrastiveSemanticReasoner(model="grok-4.6", reasoning_effort="high")`
8. wrap with arm recording/budget wrappers;
9. execute runner once;
10. always persist whatever raw artifacts exist after completion/abort;
11. never retry or auto-rerun.

Missing API key after passed preflight is `ABORTED_RUNTIME` with zero live calls; artifacts must record that without leaking environment data.

Before each provider call, a lightweight identity guard re-checks the in-process policy/prompt/schema constants against manifest values and that global call/cost ceilings have not drifted. Failure is `ABORTED_RUNTIME` before the provider call.

### Integration tests

All tests monkeypatch reasoner factories and block sockets.

Prove:

- failed preflight never reads API key and never invokes reasoner factory;
- preflight-only never writes and never constructs reasoners;
- passed preflight then missing API key records runtime abort with zero calls;
- fake live success creates the full raw artifact tree and 24 request records;
- provider failure preserves earlier artifacts and stops later calls;
- second `--live` attempt with existing `preflight.json` refuses before reasoner construction;
- output manifest/expectations are byte-unchanged after run;
- branch/core/path identity gate behavior uses injected real-looking git results, not hard-coded success.

Run:

```bash
uv run pytest -q tests/integration/test_contrastive_unseen_entrypoint.py
uv run ruff check scripts/run_contrastive_unseen_lifecycle.py tests/integration/test_contrastive_unseen_entrypoint.py
```

Commit exact message above.

---

## T8 — Whole-harness verification, code freeze, preregistration seal

This task has one final seal commit after verification.

### 1. Fresh full verification

Run from clean T7 HEAD:

```bash
uv run pytest -v
uv run ruff check .
uv run mypy src
git diff --check 1f89fc86cda463da676bf45603b86a7dcb458452..HEAD
git status --short
```

Record exact pass count and warning count.

### 2. Architecture checks

Prove with commands/source inspection:

```bash
git diff --name-only 1f89fc86cda463da676bf45603b86a7dcb458452..HEAD -- \
  src/foundry/domain src/foundry/application src/foundry/ports src/foundry/adapters
```

Expected: empty.

Also prove:

- no diff under `src/foundry/experiments/longitudinal/`;
- no diff under old 9P experiment artifact directory;
- historical and contrastive policy/prompt/schema identities recompute to frozen literals;
- `CALLS_PER_DELTA == 2` in frozen production path;
- Arm A has exactly two `propose_and_submit` sites and no retry/fallback;
- no request-path module imports `expectations`;
- zero network/live provider/model/judge calls occurred during implementation.

### 3. Final whole-branch review

Use `superpowers:requesting-code-review` on approved-spec commit `099c7e0940056f3ef909d63501f4c12853f4cf13` through current T7 HEAD. Require 0 Critical and 0 Important findings. Resolve any such finding with TDD and rerun full verification.

### 4. Generate preregistration artifacts

With clean verified T7 HEAD:

```bash
uv run python scripts/prepare_contrastive_unseen_lifecycle.py \
  --out docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1
```

Immediately verify:

```bash
git status --short
git diff --name-only
```

Exactly these two untracked/new files must exist:

```text
docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/manifest.json
docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/expectations.json
```

No other change.

Inspect/validate both JSON files and recompute their canonical hashes.

### 5. Seal commit

Commit exactly:

```bash
git add docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/manifest.json \
        docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/expectations.json
git commit -m "chore: seal 9P2 unseen lifecycle experiment"
```

The seal commit's direct parent must equal `manifest.harness_code_sha`, and the seal commit changes exactly those two files.

### 6. Fresh sealed preflight without live calls

With seal HEAD clean:

```bash
uv run python scripts/run_contrastive_unseen_lifecycle.py \
  --preflight-only \
  --frozen-sha "$(git rev-parse HEAD)" \
  --out docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1
```

Expected: every preflight gate PASS; no filesystem change.

Then:

```bash
git status --short
```

Expected empty.

Do NOT run `--live`.

### 7. Final completion report

Report:

1. starting SHA;
2. T1-T7 commit SHAs/messages;
3. final seal SHA and its parent;
4. all changed files from approved spec to seal;
5. RED evidence per implementation task;
6. targeted GREEN results;
7. full pytest exact count;
8. ruff/mypy/diff-check/status results;
9. whole-branch review verdict;
10. proof frozen core paths are unchanged;
11. proof historical 9P package/artifacts unchanged;
12. exact policy/prompt/schema identities;
13. exact evidence/schedule/ceiling manifest identities;
14. needle-set SHA and leakage skeleton count/hash summary;
15. final preflight-only gate table;
16. manifest and expectations canonical SHA256 values;
17. proof seal commit changes only two preregistration files;
18. proof zero live provider/model/judge calls;
19. remaining concerns.

Allowed final conclusion only:

`9P2 unseen-lifecycle harness locally verified and sealed; live experiment remains unauthorized pending architect verification.`

Do not push unless the user/architect separately instructs it. Do not run the live experiment.