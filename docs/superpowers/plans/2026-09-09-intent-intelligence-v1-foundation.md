# Foundry Intent Intelligence v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install the first intelligent inspection station: bounded compilation of executor-visible events into untrusted structured proposals, deterministic validation, and sealed evaluation scoring — without mutating canonical Intent State.

**Architecture:** Staged proposal pipeline (Design Alternative B). Provider-neutral `IntentIntelligence` port. Proposal plane distinct from v0 canonical semantic/event planes. Judge data never enters the intelligence path.

**Tech Stack:** Python 3.12, existing Foundry modular monolith, Pydantic frozen models, pytest, existing Task 7 evaluation harness. No new vendor SDK in Tasks 9A–9F. Task 9G adds `xai-sdk` as an adapter-layer dependency only.

**Spec:** `docs/superpowers/specs/2026-09-09-intent-intelligence-v1-design.md`

**Comparative exam (draft):** `docs/superpowers/specs/2026-09-10-intent-intelligence-comparative-exam-design.md`

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

### Task 9I-R: Comparative exam pre-registration — THIS TASK

**Status:** documentation/design only. The comparative spec remains `Draft for architectural review` until an architect Approves it.

**Files:**
- Create: `docs/superpowers/specs/2026-09-10-intent-intelligence-comparative-exam-design.md`
- Modify: `docs/superpowers/specs/2026-09-09-intent-intelligence-v1-design.md`
- Modify: `docs/superpowers/plans/2026-09-09-intent-intelligence-v1-foundation.md`

Freeze experimental rules **before** baseline code or holdouts exist.

Do not implement the baseline. Do not create holdout cases or judges. Do not make model calls. Do not modify the frozen Foundry worker, prompt, or schemas.

Contestant A is frozen at `2d75532afbbe25913d5550483d3363f3df4cb754`.

- [ ] **Step 1:** Write the comparative-exam design.
- [ ] **Step 2:** Point the v1 design and this plan at the new sequence `9I-R → 9I-A → 9J → 9K`.
- [ ] **Step 3:** Commit

```bash
git commit -m "docs: preregister Intent Intelligence comparative exam"
```

Architect review is a hard gate. Do not start 9I-A until the comparative spec is Approved.

---

### Task 9I-A: One-shot baseline and comparison plumbing

**Blocked on:** architect approval of the 9I-R comparative spec.

**Illustrative files (do not create in 9I-R):**
- Create: `src/foundry/intelligence/baseline.py`
- Create: `src/foundry/adapters/intelligence/xai_baseline.py`
- Test: `tests/unit/test_intelligence_baseline.py`
- Test: `tests/unit/test_xai_baseline_adapter.py`

Exact architecture must follow the approved comparative spec.

Rules:

- Same model (`grok-4.6`), reasoning effort (`high`), and source records as frozen Foundry.
- One semantic model call per case.
- No tools, research, persistent conversation, or judge access.
- Evaluation-only baseline payload. Do not broaden it into production proposal architecture.
- Do not modify the frozen Foundry contestant.
- Do not create holdouts.
- Do not run the comparative exam.
- Task 7 exact scoring remains a diagnostic, not the primary semantic endpoint.

- [ ] **Step 1:** Confirm the comparative spec is Approved.
- [ ] **Step 2:** TDD the baseline adapter and comparison plumbing.
- [ ] **Step 3:** Freeze baseline implementation/configuration.
- [ ] **Step 4:** Commit

```bash
git commit -m "feat: add one-shot baseline comparison harness"
```

---

### Task 9J: Freeze adjudicator and create fresh sealed holdout suite

**Blocked on:** frozen Contestant A, frozen baseline instruction/schema, frozen semantic rubric.

**Do not create holdout `judge.json` files before this task, and not in 9I-A.**

9J must:

- freeze the adjudication mechanism (blind to contestant identity; independent of contestant execution)
- create exactly 12 fresh cases: 6 greenfield, 6 brownfield
- freeze hidden expected semantic concepts, exact diagnostic subject keys, criticality, and evidence basis
- prevent contestant access to judge during execution
- not invent holdout answers in the same task that implements the baseline

Do not enumerate case answers in 9I-R. Do not copy development-fixture keys into holdouts.

- [ ] **Step 1:** Freeze adjudication mechanism.
- [ ] **Step 2:** Author and seal the 12-case suite independently of contestant implementation.
- [ ] **Step 3:** Commit process/seal artifacts only; contestants must not see hidden concepts.

```bash
git commit -m "docs: freeze adjudicator and seal comparative holdouts"
```

---

### Task 9K: Execute sealed comparative exam

**Blocked on:** 9J seal.

Run:

```text
12 cases × 2 contestants = 24 semantic model calls
```

excluding recorded infrastructure-only retries.

For each case: produce Foundry output, produce baseline output, freeze both, anonymize labels, perform semantic adjudication, freeze judgments, reveal identities, report exact + semantic + safety + efficiency metrics.

Never tune between cases or contestants. No weighted master score. No statistical-significance claim on this first suite.

- [ ] **Step 1:** Execute once per contestant per case.
- [ ] **Step 2:** Adjudicate blind, then reveal identities.
- [ ] **Step 3:** Report the metric vector. Only after 9K decide whether to change Intent Intelligence.

---

## Standing rules for every task

- Strict TDD: behavioral test first, confirm intended failure, then minimum implementation.
- Never weaken a valid test to make implementation pass.
- After every task: relevant tests plus `uv run pytest -v`, `uv run ruff check .`, `uv run mypy src`.
- No canonical mutation: no `PostgresEventStore.append` of intelligence output.
- No judge leakage into compiler, executor, or adapter.
- No provider SDK in `src/foundry/intelligence/`.
- One bounded task at a time. Task 9E is deferred. Task 9H is completed. Task 9I-R pre-registers the comparative exam as a draft; do not start 9I-A, 9J, or 9K until the comparative spec is architect-Approved and prior freeze gates are met. Do not tune the frozen Foundry worker after this pre-registration.
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
