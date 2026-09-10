# Foundry Intent Intelligence v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install the first intelligent inspection station: bounded compilation of executor-visible events into untrusted structured proposals, deterministic validation, and sealed evaluation scoring — without mutating canonical Intent State.

**Architecture:** Staged proposal pipeline (Design Alternative B). Provider-neutral `IntentIntelligence` port. Proposal plane distinct from v0 canonical semantic/event planes. Judge data never enters the intelligence path.

**Tech Stack:** Python 3.12, existing Foundry modular monolith, Pydantic frozen models, pytest, existing Task 7 evaluation harness. No new vendor SDK in Tasks 9A–9F. Task 9G adds `xai-sdk` as an adapter-layer dependency only.

**Spec:** `docs/superpowers/specs/2026-09-09-intent-intelligence-v1-design.md`

**Comparative exam (Approved — 2026-09-10):** `docs/superpowers/specs/2026-09-10-intent-intelligence-comparative-exam-design.md`

---

## File structure

Create under the existing monolith:

```text
src/foundry/intelligence/
  __init__.py
  kinds.py
  proposals.py
  input.py
  compiler.py
  validation.py
  port.py
  fake.py
  eval_adapter.py
  errors.py
  runs.py

tests/unit/
  test_intelligence_proposals.py
  test_intelligence_compiler.py
  test_intelligence_validation.py
  test_intelligence_port.py
  test_intelligence_eval_adapter.py
  test_xai_intelligence_adapter.py

tests/integration/
  test_intelligence_development_fixtures.py   # Task 9H; no judge in worker path

src/foundry/adapters/intelligence/
  __init__.py
  xai.py
```

The first empirical provider adapter is xAI Grok 4.6 under `src/foundry/adapters/intelligence/`. The kernel still must not import the vendor.

Do not write into `src/foundry/domain/semantic.py`, `events.py`, `state.py`, `closure.py`, or `adapters/postgres/`.

---

### Task 9A: Provider-neutral untrusted proposal contracts

**Files:**
- Create: `src/foundry/intelligence/__init__.py`
- Create: `src/foundry/intelligence/kinds.py`
- Create: `src/foundry/intelligence/proposals.py`
- Create: `src/foundry/intelligence/errors.py`
- Test: `tests/unit/test_intelligence_proposals.py`

**Interfaces:**
- Consumes: `SemanticKind`, `GapKind`, `RiskLevel`, `FrozenModel` from v0.
- Produces: `IntelligenceSemanticKind`, typed `SemanticProposal` union, `GapProposal`, `IntentIntelligencePayload`, `IntelligenceUsage`, `IntentIntelligenceResult`.

#### Architect-approved proposal-plane semantics

- These types are untrusted. They are not `SemanticObject` or `Gap`.
- Allowed semantic proposal kinds: INTENT, GOAL, OUTCOME, REQUIREMENT, CONSTRAINT, NON_GOAL, PREFERENCE, ASSUMPTION, CLAIM, UNKNOWN, QUESTION.
- Forbidden on proposals: authority, lifecycle, project_id, revision, created_at, provenance, event_type, event_id, fingerprint.
- Extra fields forbidden. Confidence in `[0.0, 1.0]`.
- Requirement proposals carry `statement` only. Metrics and verification needs are gap proposals, not semantic proposals.
- `CONFLICT` is not a semantic proposal kind; contradictions are `GapProposal` with `GapKind.CONTRADICTION`.
- `GapProposal` uses local `proposal_id` plus public `subject_key` (lowercase kebab-case). The worker does not emit the final evaluation fingerprint.
- The **model schema** is `IntentIntelligencePayload` only. `IntelligenceUsage` is runtime evidence attached by an adapter or fake executor, never generated as semantic content.
- A model payload that includes `usage`, cost, tokens, or wall-clock is invalid extra output.

- [ ] **Step 1: Write RED tests**

Create tests proving:

1. each allowed kind constructs with its typed payload,
2. `authority=` on a proposal is rejected,
3. `project_id=` on a proposal is rejected,
4. extra fields are rejected,
5. confidence `1.01` and `-0.1` are rejected,
6. `GapProposal` has `proposal_id` and `subject_key` and no `fingerprint` field,
7. `IntentIntelligencePayload` has no `usage` field,
8. `IntentIntelligenceResult` wraps payload plus usage,
9. `IntelligenceSemanticKind` is exactly the allowed set and is a subset of `SemanticKind`.

```bash
uv run pytest tests/unit/test_intelligence_proposals.py -v
```

Expected: FAIL because intelligence proposal modules do not exist.

- [ ] **Step 2: Implement the proposal models**

Use frozen Pydantic models, `extra="forbid"`, literal `kind`, discriminated union. Do not reuse `SemanticBase`.

- [ ] **Step 3: Verify**

```bash
uv run pytest tests/unit/test_intelligence_proposals.py -v
uv run ruff check src/foundry/intelligence tests/unit/test_intelligence_proposals.py
uv run mypy src/foundry/intelligence
```

- [ ] **Step 4: Commit**

```bash
git add src/foundry/intelligence tests/unit/test_intelligence_proposals.py
git commit -m "feat: define untrusted intelligence proposal contracts"
```

---

### Task 9B: Bounded intelligence input compiler

**Files:**
- Create: `src/foundry/intelligence/input.py`
- Create: `src/foundry/intelligence/compiler.py`
- Test: `tests/unit/test_intelligence_compiler.py`

**Interfaces:**
- Consumes: `EvalInput`, `EventEnvelope`, `EventType.USER_STATED_INTENT`, `EventType.CLAIM_INFERRED`.
- Produces: `IntelligenceSource`, `IntelligenceInput`, `compile_intelligence_input(eval_input) -> IntelligenceInput`.

#### Architect-approved compiler semantics

- Support only `USER_STATED_INTENT` and `CLAIM_INFERRED`. Any other event type fails visibly.
- Never accept `EvalExpectation` or judge paths as arguments.
- Strip authority, lifecycle, revision, created_at, and full semantic objects.
- `USER_STATED_INTENT` content is payload text; source is HUMAN / actor_id.
- `CLAIM_INFERRED` content is claim statement; source is the claim's existing provenance `source_kind` / `source_ref`.
- No repository or filesystem access.

- [ ] **Step 1: Write RED tests**

Tests must:

1. compile the greenfield `load_input` fixture to one source with the payment-platform text,
2. compile the brownfield `load_input` fixture to two claim sources without choosing a winner,
3. fail when an unsupported event type is present,
4. prove compiled sources have no `authority` attribute,
5. prove `compile_intelligence_input` does not call `load_judge`.

Do not assert hidden judge fingerprints in compiler tests.

```bash
uv run pytest tests/unit/test_intelligence_compiler.py -v
```

Expected: FAIL because compiler modules do not exist.

- [ ] **Step 2: Implement compiler**

- [ ] **Step 3: Verify**

```bash
uv run pytest tests/unit/test_intelligence_compiler.py -v
uv run ruff check src/foundry/intelligence tests/unit/test_intelligence_compiler.py
uv run mypy src/foundry/intelligence
```

- [ ] **Step 4: Commit**

```bash
git add src/foundry/intelligence/input.py src/foundry/intelligence/compiler.py tests/unit/test_intelligence_compiler.py
git commit -m "feat: compile bounded intelligence input from EvalInput"
```

---

### Task 9C: Deterministic proposal validation

**Files:**
- Create: `src/foundry/intelligence/validation.py`
- Test: `tests/unit/test_intelligence_validation.py`

**Interfaces:**
- Consumes: `IntelligenceInput`, `IntentIntelligenceResult`.
- Produces: `validate_intelligence_result(request, result) -> IntentIntelligenceResult` or raises `IntelligenceValidationError`.

Required failures (visible, no repair):

```text
duplicate semantic proposal_id
duplicate gap proposal_id
duplicate (kind, subject_key)
empty or malformed subject_key (not lowercase kebab-case)
unknown source_event_id
unknown affected_proposal_id
confidence outside [0,1] (if it somehow bypasses model construction)
disallowed semantic kind
fingerprint field on GapProposal
usage/cost/token fields on IntentIntelligencePayload
extra fields (enforced by models; keep an explicit test)
```

Do not silently rewrite malformed `subject_key` values.

- [ ] **Step 1: Write RED tests** for each failure and one valid round-trip.

```bash
uv run pytest tests/unit/test_intelligence_validation.py -v
```

Expected: FAIL because validator does not exist.

- [ ] **Step 2: Implement validator**

Do not rewrite `subject_key` or synthesize fingerprints. Do not drop invalid items. Fail the whole result. Validate the payload; usage is not model output.

- [ ] **Step 3: Verify and commit**

```bash
git commit -m "feat: validate untrusted intelligence results"
```

---

### Task 9D: IntentIntelligence port and fake test executor

**Files:**
- Create: `src/foundry/intelligence/port.py`
- Create: `src/foundry/intelligence/fake.py`
- Test: `tests/unit/test_intelligence_port.py`

**Interfaces:**
- Produces: `IntentIntelligence` Protocol with `analyze(request) -> IntentIntelligenceResult`.
- Produces: `FakeIntentIntelligence` for tests. It must **not** hardcode development-fixture judge fingerprints or canned `subject_key` answers.

The fake executor exists so 9A–9F never require network or a vendor SDK. A fake run proves plumbing, not semantic quality.

- [ ] **Step 1: RED** — protocol and fake missing.

- [ ] **Step 2: Implement**

`FakeIntentIntelligence` may echo compiled claims as claim proposals and emit no gaps, or emit caller-injected **payloads**. It attaches `IntelligenceUsage` itself as runtime/test evidence. It must not embed judge fingerprints, must not emit `fingerprint` on gaps, and must not put usage inside the model payload.

- [ ] **Step 3: Verify the fake path: compile → analyze → validate.**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add provider-neutral intelligence port and fake executor"
```

---

### Task 9E: Deterministic semantic gap detectors — DEFERRED

No code is created in this task.

Tasks 9B and 9C already own the deterministic operations currently justified by structure.

The current free-text representation is insufficient for trustworthy standalone deterministic semantic gap detection.

Revisit only after a machine-stable normalized semantic representation exists.

---

### Task 9F: Evaluation adapter

**Files:**
- Create: `src/foundry/intelligence/eval_adapter.py`
- Test: `tests/unit/test_intelligence_eval_adapter.py`

**Interfaces:**
- Consumes: validated `IntentIntelligenceResult`.
- Produces: `to_eval_prediction(result) -> EvalPrediction`.

Rules:

- Foundry constructs `fingerprint = f"{gap.kind.value}:{gap.subject_key}"`. The worker does not emit fingerprint.
- `PredictedGap` identity is then Task 7 `(kind, fingerprint)`.
- `EvalCost` copies `result.usage` (runtime evidence), never a model-supplied usage object.
- Duplicate `(kind, subject_key)` fails before mapping (validator already forbids them).
- Adapter must not import or call `load_judge`.
- Adapter must not rewrite malformed `subject_key`.

- [ ] **Step 1: RED**

- [ ] **Step 2: Implement**

- [ ] **Step 3: Prove Task 7 `score_prediction` still owns scoring.**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: adapt intelligence gap proposals to EvalPrediction"
```

---

### Task 9G: First provider adapter behind the port — APPROVED

```text
ARCHITECTURE DECISION — 2026-09-09

The first empirical IntentIntelligence provider adapter is xAI Grok 4.6.

This is an adapter-layer experiment, not a kernel dependency.

Configuration:
- provider: xAI
- model: grok-4.6
- reasoning_effort: high
- structured output: IntentIntelligencePayload
- tools: disabled
- research: disabled
- persistent conversation: disabled
- canonical mutation: forbidden

Future OpenAI, Anthropic, local, or other workers must be able to implement
the same IntentIntelligence port without modifying the kernel.
```

**Files:**
- Create: `src/foundry/adapters/intelligence/__init__.py`
- Create: `src/foundry/adapters/intelligence/xai.py`
- Test: `tests/unit/test_xai_intelligence_adapter.py` using mocked/canned provider payloads, not live secrets in git.
- Dependency: add `"xai-sdk>=1.19,<2"` to `pyproject.toml`. Do not commit `uv.lock`.

**Rules:**

- Implements `IntentIntelligence`.
- Parses model output as `IntentIntelligencePayload` only.
- Obtains tokens/cost/wall-clock from provider/runtime instrumentation and attaches `IntelligenceUsage`.
- Rejects a model payload that includes `usage` or cost fields.
- Vendor SDK, auth, and wire format stay in `adapters/`.
- `src/foundry/intelligence/` must not import the vendor.
- Invalid provider JSON fails via Task 9C, not silent repair.
- No event-store writes.
- No tools, research, retries, fallback provider, or persistent conversation.
- Do not send `fixture_id` or `project_id` to the model.

- [ ] **Step 1:** Record the approved provider decision in this plan and the design spec before coding.
- [ ] **Step 2:** TDD the adapter against canned payloads.
- [ ] **Step 3:** Commit

```bash
git commit -m "feat: add xAI Intent Intelligence adapter"
```

---

### Task 9H: Development-fixture intelligence run — COMPLETED

**Files:**
- Create: `src/foundry/intelligence/runs.py`
- Create: `tests/integration/test_intelligence_development_fixtures.py`

**Behavior:**

```text
load_input
→ compile_intelligence_input
→ IntentIntelligence.analyze
→ validate_intelligence_result
→ to_eval_prediction
→ only then load_judge
→ score_prediction
→ capture run evidence
```

The worker/compiler path must not read `judge.json`. Do not introduce a replacement fake detector stage.

Use development fixtures only:

- `evals/fixtures/greenfield/payments_vague`
- `evals/fixtures/brownfield/retry_conflict`

Brownfield must not select retry 3 or 5 as truth.

A network-free fake run proves **plumbing only**. It does not prove semantic quality and must not hardcode development-fixture `subject_key` answers.

Actual semantic-quality evaluation of the brownfield fixture requires the real intelligence adapter after Task 9G.

A live provider run is gated after 9G and was executed as first-pass development measurement. Exact Task 7 scores on development fixtures are diagnostic, not proof of semantic intelligence or generalization.

- [x] **Step 1: RED** for the runner module.
- [x] **Step 2: Implement run evidence as an explicit run record type, not as canonical events.**
- [x] **Step 3: Commit**

```bash
git commit -m "feat: run intelligence against development fixtures"
```

---

### Task 9I-R: Comparative exam pre-registration — COMPLETED

**Status:** COMPLETED. Original pre-registration committed as a draft.

Contestant A remains frozen at `2d75532afbbe25913d5550483d3363f3df4cb754`.

- [x] **Step 1:** Write the comparative-exam design.
- [x] **Step 2:** Point the v1 design and this plan at the new sequence.
- [x] **Step 3:** Commit

```bash
git commit -m "docs: preregister Intent Intelligence comparative exam"
```

---

### Task 9I-R2: Comparative exam hardening and architectural approval — COMPLETED / APPROVED

**Status:** COMPLETED / APPROVED — 2026-09-10.

Hardened the comparative spec: causal-claim correction, frozen metric formulas, neutralization, baseline structural validation, competent baseline GapKind/source-as-data rules, balanced call order, ExperimentManifest, two-phase 9K, judge commitment, adjudicator independence, structured/uncertain adjudication, serious-safety definition, and structural-failure denominator treatment.

The comparative spec status is now `Approved — 2026-09-10`.

- [x] Incorporate architect hardenings.
- [x] Self-review against the approval checklist.
- [x] Commit

```bash
git commit -m "docs: harden and approve Intent Intelligence comparative exam"
```

---

### Task 9I-A: One-shot baseline and comparison plumbing — COMPLETED

**Status:** COMPLETED.

```text
Task 9I-A1 — COMPLETED
commit d951edcf582202997be424801282606a0f15632e

Task 9I-A2 — COMPLETED
Contestant B freeze commit:
11dd47485bb6f7079cf2b31077ee7cbe988936fc

Task 9I-A3 — COMPLETED
machine-verifiable contestant freeze committed at:
04faa63f095559b7d9bca4fdfe6955c9730e056e

Contestant A — FROZEN
2d75532afbbe25913d5550483d3363f3df4cb754

Contestant B — FROZEN
11dd47485bb6f7079cf2b31077ee7cbe988936fc

Task 9I-A — COMPLETED

Task 9J — NEXT / UNBLOCKED

Task 9K — BLOCKED on 9J seal + completed ExperimentManifest
```

The A3 freeze commit `04faa63f095559b7d9bca4fdfe6955c9730e056e` is evaluation
infrastructure. It is **not** the declared freeze commit for Contestant B.
Contestant B remains frozen at `11dd47485bb6f7079cf2b31077ee7cbe988936fc`.

The freeze record is `evals/comparative/contestant-freeze.json`
(`manifest_version: contestant-freeze-v1`), verified by
`src/foundry/evaluation/experiment_manifest.py`. It commits contestant identity,
provider configuration, frozen-file digests, and the semantic treatment components
(system instructions, payload schemas, source renderers), plus the evaluation base
(comparative-spec commit and digest, `comparison.py` digest, `BlindPrediction`
schema digest).

It deliberately contains **no** holdout, judge, adjudicator, execution-order,
result, or score commitment. Those artifacts do not exist yet and are not stubbed.
Task 9J completes the full `ExperimentManifest` on top of this record:

```text
ExperimentManifest
=
ContestantFreezeManifest
+ holdout commitments
+ hidden judge commitment
+ adjudication mechanism
+ execution-order commitment
```

Verification is read-only. Only `write_contestant_freeze` may emit a freeze
artifact; Task 9K must call verify, never write. A mismatch raises
`ExperimentFreezeViolation` and aborts comparative execution rather than
regenerating hashes. Upgrading `xai-sdk` away from the frozen `1.19.0` invalidates
the freeze until a new experimental version is intentionally declared.

Implement at least:

```text
provider-neutral baseline contracts
baseline structural validator
xAI Grok 4.6 baseline adapter
shared/verified source rendering
neutral BlindPrediction representation
contestant-output neutralization
experiment manifest primitives
network-free comparison plumbing tests
```

**Illustrative files:**
- Create: `src/foundry/intelligence/baseline.py`
- Create: `src/foundry/adapters/intelligence/xai_baseline.py`
- Test: `tests/unit/test_intelligence_baseline.py`
- Test: `tests/unit/test_xai_baseline_adapter.py`

Exact architecture must follow the approved comparative spec.

Rules:

- Same model (`grok-4.6`), reasoning effort (`high`), and source records as frozen Foundry.
- Baseline MUST receive the same public GapKind definitions and source-as-data protection.
- One semantic model call per case. No tools, research, persistent conversation, or judge access.
- Equivalent structural validation. No silent repair. No semantic retry of invalid payloads.
- Evaluation-only baseline payload. Do not broaden it into production proposal architecture.
- Do not modify the frozen Foundry contestant.
- Do not create holdouts or judges.
- Do not run the comparative exam.
- Task 7 exact scoring remains a diagnostic, not the primary semantic endpoint.

Then freeze Contestant B.

- [x] **Step 1:** TDD baseline contracts, validator, adapter, neutralization, and manifest primitives.
- [x] **Step 2:** Freeze baseline implementation/configuration.
- [x] **Step 3:** Commit

```bash
git commit -m "feat: add baseline comparison contracts"
git commit -m "feat: add xAI one-shot baseline adapter"
git commit -m "feat: freeze comparative contestants"
```

---

### Task 9J: Freeze adjudicator and create fresh sealed holdout suite

Task 9J is executed as three separate review gates. The single undifferentiated 9J
status is replaced by this explicit sequence:

```text
9J1  Freeze adjudication/rubric + build sealing infrastructure
 |
9J2  Fresh-session authoring of 12 holdouts + hidden judge + randomization
 |
9J3  Independent pre-exam audit and final seal
 |
9K   Execute the comparative exam
```

```text
Task 9J1 — COMPLETED
a83bbaab07537e70e3195ad0a5a7116e59bdf40b

Task 9J2 — COMPLETED

- 12 fresh sealed cases authored
- 6 greenfield / 6 brownfield
- hidden expected concepts authored outside repository
- judge commitment frozen
- case sequence frozen
- execution order frozen
- blind-label assignment frozen
- complete ExperimentManifest written
- Phase-1 seal verifier passes
- hidden judge commitment verifier passes
- no contestant calls executed
- no contestant/rubric/protocol changes

Task 9J3 — NEXT / UNBLOCKED
Must begin in a fresh Claude Code session.

Task 9K — BLOCKED
until 9J3 independently audits and approves the sealed exam.
```

#### Task 9J1 — COMPLETED

Contestant B is frozen at `11dd47485bb6f7079cf2b31077ee7cbe988936fc` and the
contestant freeze is machine-verifiable at `evals/comparative/contestant-freeze.json`.

9J1 froze the **rules of judging before the exam questions exist**:

```text
Contestants             FROZEN
Semantic rubric         FROZEN
Adjudication method     FROZEN
Judge schemas           FROZEN
Holdout schemas         FROZEN
Sealing machinery       BUILT

Actual holdouts         DO NOT EXIST
Expected concepts       DO NOT EXIST
Hidden judge bundle     DOES NOT EXIST
Execution assignment    DOES NOT EXIST
Full ExperimentManifest DOES NOT EXIST
Contestant outputs      DO NOT EXIST
```

Committed by 9J1:

- `src/foundry/evaluation/comparative_protocol.py` — `HoldoutFamily`,
  `ConceptCriticality`, `ExpectedConcept`, `HiddenJudgeCase`, `HiddenJudgeBundle`,
  `PredictionDisposition`, `SafetyLabel` (+ the exact serious subset),
  `AdjudicationState`, `ConceptJudgment`, `PredictionJudgment`, `SystemAdjudication`,
  `BlindAdjudicationPacket`, the structural adjudication validator, the exact Task 7
  adapter, and the two frozen protocol builders.
- `src/foundry/evaluation/sealed_exam_manifest.py` — holdout/execution/judge
  commitment schemas, the full `ExperimentManifest` type, `verify_phase1_experiment`,
  and the separate Phase-2 `verify_revealed_judge_bundle`.
- `evals/comparative/protocol/adjudication-mechanism.json`
  (`gpt-5.6-sol-blind-primary-human-uncertain-v1`).
- `evals/comparative/protocol/semantic-rubric.json` (`intent-semantic-rubric-v1`).

The adjudication mechanism is a **protocol declaration only**. No OpenAI, Anthropic,
or xAI dependency was added and no model call was made. `Grok 4.6` is recorded as
forbidden from being the sole adjudicator.

Phase separation is enforced in the API, not by convention:
`verify_phase1_experiment` takes no judge bundle or judge path argument and verifies
only the judge **commitment**. Revealing judge contents requires the separate
Phase-2 `verify_revealed_judge_bundle`, which is called only after contestant
outputs freeze.

#### Task 9J2 — COMPLETED

Authored in a fresh Claude Code session starting from the exact 9J1 protocol-freeze
commit `a83bbaab07537e70e3195ad0a5a7116e59bdf40b`. The session that built the judging
rules did not author the exam questions, and the authoring session did not read either
contestant, the development fixtures, or any prior contestant output.

The visible exam is `evals/comparative/holdouts/case-001` through `case-012`, each
holding exactly one `input.json` under opaque fixture IDs `H-001` to `H-012`. Every
case parses through `load_input` and compiles through `compile_intelligence_input`
using only `USER_STATED_INTENT` and `CLAIM_INFERRED` evidence. No contestant was
instantiated or called.

Sealed in this task:

- `evals/comparative/holdout-inputs.json` — per-case family and raw-byte SHA-256,
  in the frozen Phase-1 execution sequence produced by a single
  `secrets.SystemRandom()` shuffle.
- `evals/comparative/execution-assignment.json` — a single shuffle of twelve
  2x2 cross-balanced templates, giving 6 Foundry-first / 6 Baseline-first and
  6 Foundry=SYSTEM-A / 6 Foundry=SYSTEM-B.
- `evals/comparative/experiment-manifest.json` — the complete `ExperimentManifest`
  committing contestant-freeze bytes, both protocol module digests, the mechanism
  and rubric bytes, both randomization manifests, and the hidden judge commitment.

The hidden expected concepts live **outside** the repository at
`../.foundry-sealed-evals/intent-intelligence-v1/hidden-judge.json` and are not
tracked, copied, or symlinked into git. The repository carries only the
`canonical-json-v1` SHA-256 commitment. `verify_phase1_experiment` passes without
reading that file; the separate Phase-2 `verify_revealed_judge_bundle` confirms the
external file matches the commitment and is grounded in the visible inputs.

The suite is frozen. Do not tune a case, a concept, or the ordering after contestant
outputs begin. A genuine judge defect discovered later invalidates that case and is
reported as an exclusion; it is not silently repaired.

9J2 MUST NOT modify:

- either contestant
- the approved comparative spec
- the 9J1 adjudication mechanism
- the 9J1 semantic rubric
- 9J1 protocol/sealing semantics

Any such change requires stopping and returning to architectural review.

**Do not create holdout `judge.json` files before this task, and not in 9I-A or 9J1.**

**Do not create holdout `judge.json` files before this task, and not in 9I-A.**

9J must:

- select/freeze independent adjudication mechanism (`Grok 4.6` may not be the sole semantic adjudicator)
- create exactly 12 fresh cases: 6 greenfield, 6 brownfield
- hidden expected concepts with quality checks (`concept_id`, `semantic_description`, `primary_gap_kind`, `criticality`, `evidence_basis`, materiality rationale)
- judge bundle canonical serialization and SHA-256 commitment
- balanced randomized A/B call ordering (6 Foundry-first, 6 Baseline-first)
- holdout input hashes
- completion of ExperimentManifest
- prevent contestant access to judge during execution
- not invent holdout answers in the same task that implements the baseline

Do not enumerate case answers in 9I-A. Do not copy development-fixture keys into holdouts. Holdouts do not yet exist.

- [x] **Step 1 (9J1):** Freeze adjudication mechanism, semantic rubric, and sealing schemas.
- [x] **Step 2 (9J2):** Author and seal the 12-case suite independently of contestant implementation.
- [ ] **Step 3 (9J3):** Independent pre-exam audit, then final seal.

```bash
git commit -m "feat: freeze comparative adjudication protocol"   # 9J1
git commit -m "docs: seal comparative holdouts and hidden judge"  # 9J2
```

---

### Task 9K: Execute sealed comparative exam

**Status:** BLOCKED on a successful 9J3 audit and the completed `ExperimentManifest`.

Two-phase execution.

**Phase 1:**

```text
verify ExperimentManifest
execute 24 contestant calls back-to-back under frozen order
freeze outputs
neutralize
hash outputs
no judge access
```

**Phase 2:**

```text
reveal/verify judge bundle
blind semantic adjudication
freeze judgments
reveal contestant identities
compute exact diagnostic
compute semantic metrics
compute minimality metrics
compute safety metrics
compute efficiency metrics
report trade-offs
```

No tuning. No semantic reruns after judge reveal. No weighted master score. No statistical-significance or causal-certainty claim on this first suite.

- [ ] **Step 1:** Verify manifest, then Phase 1 execution.
- [ ] **Step 2:** Phase 2 adjudication and reporting.
- [ ] **Step 3:** Only after the complete 9K report decide whether to change Intent Intelligence.

---

## Standing rules for every task

- Strict TDD: behavioral test first, confirm intended failure, then minimum implementation.
- Never weaken a valid test to make implementation pass.
- After every task: relevant tests plus `uv run pytest -v`, `uv run ruff check .`, `uv run mypy src`.
- No canonical mutation: no `PostgresEventStore.append` of intelligence output.
- No judge leakage into compiler, executor, or adapter.
- No provider SDK in `src/foundry/intelligence/`.
- One bounded task at a time. Task 9E is deferred. Task 9H is completed. Task 9I-R and 9I-R2 are completed; the comparative spec is Approved — 2026-09-10. Task 9I-A is completed; both contestants are frozen and the freeze is machine-verifiable. Task 9J1 is completed; the adjudication mechanism and semantic rubric are frozen before any holdout exists. Task 9J2 is completed; the 12 sealed holdouts, the hidden judge commitment, the frozen case sequence, the execution assignment, and the complete ExperimentManifest exist. Task 9J3 is next/unblocked and must start in a fresh session. Task 9K is blocked until the 9J3 audit passes. Do not tune the frozen Foundry worker after this freeze.
- Do not implement the Intelligence Router, general Context Compiler, or research fabric in this plan.

---

## Architecture questions

```text
ARCHITECTURE DECISION — 2026-09-09

The first empirical IntentIntelligence provider adapter is xAI Grok 4.6.

This is an adapter-layer experiment, not a kernel dependency.

Configuration:
- provider: xAI
- model: grok-4.6
- reasoning_effort: high
- structured output: IntentIntelligencePayload
- tools: disabled
- research: disabled
- persistent conversation: disabled
- canonical mutation: forbidden

Future OpenAI, Anthropic, local, or other workers must be able to implement
the same IntentIntelligence port without modifying the kernel.
```

The kernel depends on `IntentIntelligence`. xAI/Grok is Worker #1, not part of the kernel. Task 9G is approved. Tasks 9A–9F are unchanged.
