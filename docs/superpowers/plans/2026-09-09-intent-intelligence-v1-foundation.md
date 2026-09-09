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

### Task 9E: Deterministic first-pass gap detectors

**Files:**
- Create: `src/foundry/intelligence/detectors.py`
- Test: `tests/unit/test_intelligence_detectors.py`

**Interfaces:**
- Consumes: `IntelligenceInput`.
- Produces: `detect_deterministic_gaps(request) -> tuple[GapProposal, ...]`.

Allowed deterministic detections in v1 are only structure-provable:

- exact duplicate source contents
- exact duplicate proposal contents
- unsupported event rejection
- schema/reference checks

Forbidden:

- free-text contradiction detection (v0 claims are free-text `statement` with no machine-stable subject key)
- English phrase ontologies for “very fast” / “never loses money”
- inventing jurisdiction/currency from regex
- promising brownfield retry 3 vs 5 as a deterministic detector result

Brownfield contradiction and missing-authority recognition is the **semantic intelligence worker/model** job after Task 9G. Detectors must not pick 3 or 5.

If a later stage introduces a trusted machine-stable subject/property key, contradiction over that structure may become deterministic. v1 does not invent that ontology.

Detector output is still untrusted `GapProposal` (`proposal_id` + `subject_key`) and must pass Task 9C validation.

- [ ] **Step 1: RED tests** for exact-duplicate sources and a test that detectors do **not** flag greenfield “very fast” or brownfield retry statements as contradictions.

- [ ] **Step 2: Implement only the smallest trustworthy structural detectors.**

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
- Parses model output as `IntentIntelligencePayload` only.
- Obtains tokens/cost/wall-clock from provider/runtime instrumentation and attaches `IntelligenceUsage`.
- Rejects a model payload that includes `usage` or cost fields.
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

A network-free fake-plus-detectors run proves **plumbing only**. It does not prove semantic quality and must not hardcode development-fixture `subject_key` answers.

Actual semantic-quality evaluation of the brownfield fixture requires the real intelligence adapter after Task 9G.

A live provider run is optional and must be explicitly gated after 9G.

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
- Foundry still constructs `fingerprint = f"{kind.value}:{subject_key}"` for the Task 7 scorer
- the protocol must handle legitimate semantic-equivalent wording without exposing the answer key
- this task names that requirement; it does not implement a matching algorithm in this plan's earlier tasks

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

The kernel depends on `IntentIntelligence`. The first live adapter (Grok, OpenAI, Anthropic, or other) is an adapter-layer experiment, not a core dependency. Task 9G is blocked until this is decided. Tasks 9A–9F are not blocked.
