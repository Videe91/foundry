# Foundry Intent Intelligence v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install the first intelligent inspection station: bounded compilation of executor-visible events into untrusted structured proposals, deterministic validation, and sealed evaluation scoring — without mutating canonical Intent State.

**Architecture:** Staged proposal pipeline (Design Alternative B). Provider-neutral `IntentIntelligence` port. Proposal plane distinct from v0 canonical semantic/event planes. Judge data never enters the intelligence path.

**Tech Stack:** Python 3.12, existing Foundry modular monolith, Pydantic frozen models, pytest, existing Task 7 evaluation harness. No new vendor SDK in Tasks 9A–9F.

**Spec:** `docs/superpowers/specs/2026-09-09-intent-intelligence-v1-design.md`

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
  detectors.py
  eval_adapter.py
  errors.py
  runs.py

tests/unit/
  test_intelligence_proposals.py
  test_intelligence_compiler.py
  test_intelligence_validation.py
  test_intelligence_port.py
  test_intelligence_detectors.py
  test_intelligence_eval_adapter.py

tests/integration/
  test_intelligence_development_fixtures.py   # Task 9H; no judge in worker path
```

Provider adapter paths are deferred to Task 9G after the architecture question is answered.

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
- Produces: `IntelligenceSemanticKind`, typed `SemanticProposal` union, `GapProposal`, `IntelligenceUsage`, `IntentIntelligenceResult`.

#### Architect-approved proposal-plane semantics

- These types are untrusted. They are not `SemanticObject` or `Gap`.
- Allowed semantic proposal kinds: INTENT, GOAL, OUTCOME, REQUIREMENT, CONSTRAINT, NON_GOAL, PREFERENCE, ASSUMPTION, CLAIM, UNKNOWN, QUESTION.
- Forbidden on proposals: authority, lifecycle, project_id, revision, created_at, provenance, event_type, event_id.
- Extra fields forbidden. Confidence in `[0.0, 1.0]`.
- Requirement proposals carry `statement` only. Metrics and verification needs are gap proposals, not semantic proposals.
- `CONFLICT` is not a semantic proposal kind; contradictions are `GapProposal` with `GapKind.CONTRADICTION`.

- [ ] **Step 1: Write RED tests**

Create tests proving:

1. each allowed kind constructs with its typed payload,
2. `authority=` on a proposal is rejected,
3. `project_id=` on a proposal is rejected,
4. extra fields are rejected,
5. confidence `1.01` and `-0.1` are rejected,
6. `IntentIntelligenceResult` holds disjoint semantic and gap tuples plus usage,
7. `IntelligenceSemanticKind` is exactly the allowed set and is a subset of `SemanticKind`.

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
duplicate proposal_id
duplicate gap fingerprint
unknown source_event_id
unknown affected_proposal_id
confidence outside [0,1] (if it somehow bypasses model construction)
disallowed semantic kind
extra fields (enforced by models; keep an explicit test)
```

- [ ] **Step 1: Write RED tests** for each failure and one valid round-trip.

```bash
uv run pytest tests/unit/test_intelligence_validation.py -v
```

Expected: FAIL because validator does not exist.

- [ ] **Step 2: Implement validator**

Do not rewrite fingerprints. Do not drop invalid items. Fail the whole result.

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
- Produces: `FakeIntentIntelligence` for tests. It must **not** hardcode development-fixture judge fingerprints.

The fake executor exists so 9A–9F never require network or a vendor SDK.

- [ ] **Step 1: RED** — protocol and fake missing.

- [ ] **Step 2: Implement**

`FakeIntentIntelligence` may echo compiled claims as claim proposals and emit no gaps, or emit caller-injected results. It must not embed `AMBIGUITY:never-loses-money` or other judge fingerprints.

- [ ] **Step 3: Verify the fake path: compile → analyze → validate.**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add provider-neutral intelligence port and fake executor"
```

---

### Task 9E: Deterministic first-pass gap detectors

**Files:**
- Create: `src/foundry/intelligence/detectors.py`
- Test: `tests/unit/test_intelligence_detectors.py`

**Interfaces:**
- Consumes: `IntelligenceInput`.
- Produces: `detect_deterministic_gaps(request) -> tuple[GapProposal, ...]`.

Allowed deterministic detections in v1:

- two or more compiled `CLAIM_INFERRED` sources whose statements disagree as already-typed observations of the same subject when the test constructs that situation (brownfield retry 3 vs 5 must be detectable as CONTRADICTION + MISSING_AUTHORITY without picking a winner)
- exact duplicate source contents

Forbidden:

- English phrase ontologies for “very fast” / “never loses money”
- inventing jurisdiction/currency from regex

Detector output is still untrusted `GapProposal` and must pass Task 9C validation.

- [ ] **Step 1: RED tests** including brownfield compile → detect contradiction and missing authority, and a test that detectors do not flag the greenfield payment sentence via canned phrases.

- [ ] **Step 2: Implement the smallest trustworthy detectors.**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: add deterministic first-pass gap detectors"
```

---

### Task 9F: Evaluation adapter

**Files:**
- Create: `src/foundry/intelligence/eval_adapter.py`
- Test: `tests/unit/test_intelligence_eval_adapter.py`

**Interfaces:**
- Consumes: validated `IntentIntelligenceResult`.
- Produces: `to_eval_prediction(result) -> EvalPrediction`.

Rules:

- `PredictedGap` identity is `(kind, fingerprint)` from each `GapProposal`.
- `EvalCost` copies `IntelligenceUsage` fields.
- Duplicate fingerprints fail before mapping (validator already forbids them).
- Adapter must not import or call `load_judge`.

- [ ] **Step 1: RED**

- [ ] **Step 2: Implement**

- [ ] **Step 3: Prove Task 7 `score_prediction` still owns scoring.**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: adapt intelligence gap proposals to EvalPrediction"
```

---

### Task 9G: First provider adapter behind the port

**Blocked on:**

```text
ARCHITECTURE QUESTION: first empirical provider adapter choice
```

Do not start this task until that question is decided.

When unblocked:

**Files (illustrative, adjust to the chosen adapter name):**
- Create: `src/foundry/adapters/intelligence/<provider>.py`
- Test: `tests/unit/test_intelligence_<provider>_adapter.py` using recorded/canned provider payloads, not live secrets in git.

**Rules:**

- Implements `IntentIntelligence`.
- Vendor SDK, auth, and wire format stay in `adapters/`.
- `src/foundry/intelligence/` must not import the vendor.
- Invalid provider JSON fails via Task 9C, not silent repair.
- No event-store writes.

- [ ] **Step 1:** Record the approved provider decision in `foundry/decisions` or the plan's decision note before coding.
- [ ] **Step 2:** TDD the adapter against canned payloads.
- [ ] **Step 3:** Commit

```bash
git commit -m "feat: add first intelligence provider adapter behind the port"
```

---

### Task 9H: Development-fixture intelligence run

**Files:**
- Create: `src/foundry/intelligence/runs.py`
- Create: `tests/integration/test_intelligence_development_fixtures.py`

**Behavior:**

```text
load_input(fixture_dir)
→ compile_intelligence_input
→ deterministic detectors
→ optional IntentIntelligence.analyze
→ validate_intelligence_result
→ to_eval_prediction
→ load_judge (only after prediction exists)
→ score_prediction
→ persist evaluation-run evidence outside intent_events
```

The worker/compiler path must not read `judge.json`.

Use development fixtures only:

- `evals/fixtures/greenfield/payments_vague`
- `evals/fixtures/brownfield/retry_conflict`

Brownfield must not select retry 3 or 5 as truth.

This task may use `FakeIntentIntelligence` plus detectors so it remains network-free. A live provider run is optional and must be explicitly gated after 9G.

- [ ] **Step 1: RED** for the runner module.
- [ ] **Step 2: Implement run evidence as files or an explicit run record type, not as canonical events.**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat: run intelligence against sealed development fixtures"
```

---

### Task 9I: One-shot baseline runner

**Files:**
- Create: `src/foundry/intelligence/baseline.py`
- Test: `tests/unit/test_intelligence_baseline.py`

Both Foundry pipeline and one-shot baseline receive the same `IntelligenceInput` (or equivalent visible content). Neither receives the judge.

Compare Task 7 metrics only. No weighted master score.

The baseline is an experiment, not the production architecture.

Provider choice follows the same architecture question as 9G. Until then, the baseline can be a protocol plus a fake that returns a single unstructured-then-parsed stub **without** judge fingerprints.

- [ ] **Step 1: RED**
- [ ] **Step 2: Implement the comparison harness, not Alternative A as the kernel.**
- [ ] **Step 3: Commit**

```bash
git commit -m "feat: add one-shot baseline comparison harness"
```

---

### Task 9J: Fresh sealed holdout evaluation protocol

**Files:**
- Create: `docs/superpowers/specs/2026-09-09-intent-intelligence-holdout-protocol.md`
- Optionally: `evals/holdout/README.md` describing process only

**Do not create holdout `judge.json` files in this task.**

The protocol must state:

- holdout judges are authored and frozen independently of the implementation worker
- holdout `input.json` is executor-visible only
- development fixtures cannot prove general quality
- scoring remains Task 7 `score_prediction`
- identity remains `(GapKind, fingerprint)`

- [ ] **Step 1: Write the protocol document.**
- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-09-09-intent-intelligence-holdout-protocol.md
git commit -m "docs: define sealed holdout evaluation protocol"
```

---

## Standing rules for every task

- Strict TDD: behavioral test first, confirm intended failure, then minimum implementation.
- Never weaken a valid test to make implementation pass.
- After every task: relevant tests plus `uv run pytest -v`, `uv run ruff check .`, `uv run mypy src`.
- No canonical mutation: no `PostgresEventStore.append` of intelligence output.
- No judge leakage into compiler, executor, detectors, or adapter.
- No provider SDK in `src/foundry/intelligence/`.
- One bounded task at a time. Do not start 9G before the provider architecture question is answered.
- Do not implement the Intelligence Router, general Context Compiler, or research fabric in this plan.

---

## Architecture questions

```text
ARCHITECTURE QUESTION: first empirical provider adapter choice
```

The kernel depends on `IntentIntelligence`. The first live adapter (Grok, OpenAI, Anthropic, or other) is an adapter-layer experiment, not a core dependency. Task 9G is blocked until this is decided.
