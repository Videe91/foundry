# 9P2 Contrastive Semantic Assimilation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved 9P2 Contrastive Semantic Context Compiler v0 and prove locally that structurally rehydrated history fixes the Track A semantic-correction failure without adding deterministic semantic authority, a third model call, or whole-history reconstruction.

**Architecture:** Preserve the existing two-call semantic assimilation loop. Add provider-neutral ephemeral comparison context to `ReasoningRequest`; compile it only from explicit evidence lineage and current effective-evidence edges; render deterministic bounded unified diffs; give Call 1 active claim profiles; give Call 2 both the Call-1 decision neighbourhood and structurally touched existing addresses. AI continues to decide meaning. Foundry only decides which structurally connected history is shown and whether the request is inside support bounds.

**Tech Stack:** Python 3.12, Pydantic v2 frozen models, `difflib`, existing event-sourced semantic state/governor, pytest, ruff, mypy, xAI adapter with fake transport only in this plan.

**Spec:** `docs/superpowers/specs/2026-09-12-contrastive-semantic-assimilation-design.md`

**Approved design base:** `02ffde24826e12bec726a1e21606861e08bdbaf7`

**Runtime rule for this plan:** ZERO live provider/model/judge calls. The separate unseen scientific 9P2 experiment is intentionally not designed or run here. After this implementation is verified, a separate preregistration plan must freeze an unseen lifecycle before any live call.

---

## 0. Global constraints

1. **Constitution and approved spec outrank this plan.** If this plan conflicts with `FOUNDRY_CONSTITUTION.md` or the approved 9P2 design, stop and report `ARCHITECTURE QUESTION:` rather than improvising.
2. **AI understands meaning; Foundry governs meaning.** No production function may classify a transition as support, correction, conflict, or new meaning. Deterministic code may follow only explicit structural edges.
3. **No semantic retrieval in 9P2.** No embeddings, lexical similarity, descriptor equality, fuzzy matching, source-name ranking, heuristic hunk selection, or semantic top-K.
4. **No whole-history fallback.** Unsupported context size fails before the provider call. Never truncate, summarize, or silently resend the predecessor artifact wholesale.
5. **Historical comparison material is non-citable.** Only `ReasoningRequest.evidence` is the admissible evidence-id set for drafts. Existing adapter reference validation remains the enforcement boundary.
6. **Exactly two frontier calls per successful delta.** Do not add a classification/reconciliation/repair call.
7. **No new durable semantic judgment kinds.** Existing `BIND_TO_ADDRESS`, `CREATE_ADDRESS`, `SUPPORTS_CLAIM`, `ASSERT_CLAIM`, `SUPERSEDE`, and `CONFLICTS_WITH` semantics remain unchanged.
8. **No durable comparison-context state.** `ComparisonContext` is request-only. Do not add event types, reducer fields, database columns, semantic-state fields, or a second ledger for it.
9. **Claims and addresses remain immutable.** Corrections are new claims plus governed supersession.
10. **Keep the existing support boundary:** 200 active in-scope addresses. At 201, refuse before a provider call. Do not add a fallback retrieval branch.
11. **Locked context limits:** maximum 65,536 Unicode characters per rendered transition diff; maximum 131,072 Unicode characters for the canonical rendered comparison-context JSON in one request.
12. **Unified diff contract:** line based; `difflib.unified_diff`; exactly 3 unchanged context lines per hunk; stable labels from evidence ids; deterministic for identical inputs.
13. **Preserve 9P history.** Do not edit `docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/**`. The completed 9P record is immutable.
14. **Preserve the frozen 9P xAI policy.** `POLICY_VERSION == "intent-v2-9p-v4"`, `SYSTEM_INSTRUCTION`, and `SYSTEM_INSTRUCTION_SHA256 == 24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1` remain valid for `XAISemanticReasoner`. 9P2 gets a distinct contrastive policy/class rather than rewriting the historical 9P policy.
15. **Provider output schema is unchanged.** `SEMANTIC_OUTPUT_SCHEMA_SHA256` must remain `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851` because 9P2 changes model input context/guidance, not the draft output contract.
16. **Strict TDD per implementation task:** RED for the intended missing behavior -> minimum GREEN -> refactor only while green -> task verification -> commit.
17. **No network in tests.** Existing socket guards stay; new test modules that touch adapters must block sockets explicitly.
18. **One bounded task at a time.** Do not pre-implement later tasks. If a task reveals an architecturally material gap, stop.

---

## 1. File map

| Path | Change | Task |
|---|---|---|
| `src/foundry/ports/semantic_reasoner.py` | MODIFY — provider-neutral comparison-context request contract | T1 |
| `tests/unit/test_comparison_context_contract.py` | NEW | T1 |
| `src/foundry/application/context_errors.py` | NEW — shared bounded-context refusal | T2 |
| `src/foundry/application/contrastive_diff.py` | NEW — deterministic bounded unified diff | T2 |
| `tests/unit/test_contrastive_diff.py` | NEW | T2 |
| `src/foundry/application/contrastive_context.py` | NEW — structural transition compiler | T3 |
| `tests/unit/test_contrastive_context.py` | NEW | T3 |
| `src/foundry/application/assimilation_context.py` | MODIFY — Call 1 claims/context; Call 2 contrastive context; re-export `ContextUnsupported` | T4 |
| `src/foundry/application/incremental_assimilation.py` | MODIFY — structurally widen Call 2 claim neighbourhood, still two calls | T4 |
| `tests/unit/test_assimilation_context.py` | MODIFY — replace 9P zero-reread assertions with 9P2 bounded rehydration assertions | T4 |
| `tests/unit/test_incremental_assimilation.py` | MODIFY — prove two-call wiring and touched-address continuity | T4 |
| `src/foundry/adapters/semantics/xai_reasoner.py` | MODIFY — render comparison context; add isolated 9P2 contrastive policy/class | T5 |
| `tests/unit/test_xai_lifecycle_prompt.py` | MODIFY — rendered context and contrastive guidance | T5 |
| `tests/unit/test_xai_lifecycle_drafts.py` | MODIFY — historical predecessor remains non-citable | T5 |
| `tests/unit/test_xai_semantic_reasoner.py` | MODIFY — contrastive class fingerprint/system-message isolation | T5 |
| `tests/unit/test_9p2_track_a_regression.py` | NEW — real governor correction/supersession/blast-radius regression | T6 |

Do **not** modify semantic domain models, admission rules, reducer transition semantics, event types, persistence adapters, old experiment artifacts, or old 9P expectations to make 9P2 work.

---

## 2. Task T0 — Isolated execution workspace and baseline

No production change and no commit.

- [ ] Read `FOUNDRY_CONSTITUTION.md`, `AGENTS.md`, the approved 9P2 spec, and this plan before editing.
- [ ] Use `superpowers:using-git-worktrees` to create an isolated implementation worktree from the branch tip that contains this plan. Do not implement in an unrelated or stale worktree.
- [ ] Verify branch and cleanliness:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected: the intended 9P2 implementation branch/worktree and no uncommitted files.

- [ ] Run the pre-change targeted baseline:

```bash
uv run pytest -q \
  tests/unit/test_assimilation_context.py \
  tests/unit/test_incremental_assimilation.py \
  tests/unit/test_xai_lifecycle_prompt.py \
  tests/unit/test_xai_lifecycle_drafts.py \
  tests/unit/test_xai_semantic_reasoner.py \
  tests/unit/test_xai_pair_contract.py \
  tests/unit/test_xai_decimal_contract.py
```

Expected: PASS before T1. If baseline is not green, stop and use `superpowers:systematic-debugging`; do not mix a pre-existing failure into 9P2.

---

## 3. Task T1 — Provider-neutral comparison-context contract

**Commit:** `feat: add contrastive reasoning context contract`

### 3.1 Files

- Create `tests/unit/test_comparison_context_contract.py` first.
- Modify `src/foundry/ports/semantic_reasoner.py` only after RED is observed.

### 3.2 RED tests

Add tests that import these public names from `foundry.ports.semantic_reasoner`:

```python
class ContextRelation(StrEnum):
    SUPERSEDES = "SUPERSEDES"
    EFFECTIVE_EVIDENCE_OF = "EFFECTIVE_EVIDENCE_OF"
    CLAIM_AT_ADDRESS = "CLAIM_AT_ADDRESS"
    ACTIVE_CLAIM_PROFILE = "ACTIVE_CLAIM_PROFILE"

class ContextInclusionEdge(FrozenModel):
    source_id: str = Field(min_length=1)
    relation: ContextRelation
    target_id: str = Field(min_length=1)

class EvidenceTransitionContext(FrozenModel):
    current_evidence_id: str = Field(min_length=1)
    predecessor_evidence_id: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)
    historical_diff: str
    touched_claim_ids: tuple[str, ...] = ()
    touched_address_ids: tuple[str, ...] = ()
    inclusion_edges: tuple[ContextInclusionEdge, ...] = Field(min_length=1)

class ComparisonContext(FrozenModel):
    transitions: tuple[EvidenceTransitionContext, ...] = ()
    active_claim_profile_edges: tuple[ContextInclusionEdge, ...] = ()
```

Extend `ReasoningRequest` with:

```python
comparison_context: ComparisonContext = Field(default_factory=ComparisonContext)
```

Required tests:

- [ ] default `ReasoningRequest(...).comparison_context == ComparisonContext()` so existing non-contrastive callers remain valid;
- [ ] all new models are frozen and `extra="forbid"` through `FrozenModel`;
- [ ] blank ids / blank `artifact_ref` fail validation;
- [ ] `historical_diff=""` is legal because a superseding version may be byte-identical while still carrying explicit lineage;
- [ ] transition `inclusion_edges` must be non-empty;
- [ ] serialization is deterministic Pydantic JSON data, with no provider-specific field;
- [ ] there is no semantic-result field such as `classification`, `correction`, `supports`, `confidence`, `authority`, or `verdict` anywhere in the contract.

Run RED:

```bash
uv run pytest -q tests/unit/test_comparison_context_contract.py
```

Expected: collection/import failure because the contract does not exist yet.

### 3.3 Minimum GREEN implementation

In `ports/semantic_reasoner.py`:

- import `StrEnum` from `enum`;
- add the four models above before `ReasoningRequest`;
- add only the `comparison_context` field to `ReasoningRequest`;
- keep `SemanticReasoner` protocol unchanged;
- update the module/request docstrings: comparison context is bounded, request-only structural history; it is not evidence and not semantic authority.

Do not put these types in `domain/`: they are worker request context, not durable domain truth.

Run GREEN:

```bash
uv run pytest -q tests/unit/test_comparison_context_contract.py tests/unit/test_xai_semantic_reasoner.py
uv run mypy src/foundry/ports/semantic_reasoner.py
```

- [ ] Commit exactly:

```bash
git add src/foundry/ports/semantic_reasoner.py tests/unit/test_comparison_context_contract.py
git commit -m "feat: add contrastive reasoning context contract"
```

---

## 4. Task T2 — Deterministic bounded old-to-new diff

**Commit:** `feat: add bounded contrastive evidence diff`

### 4.1 Files

Create:

- `src/foundry/application/context_errors.py`
- `src/foundry/application/contrastive_diff.py`
- `tests/unit/test_contrastive_diff.py`

### 4.2 Shared refusal

`context_errors.py` contains only:

```python
class ContextUnsupported(RuntimeError):
    """The exact structurally selected context cannot be represented inside a locked support bound."""
```

No semantic policy belongs in this exception module.

### 4.3 Diff contract

`contrastive_diff.py` exports:

```python
DIFF_CONTEXT_LINES: Final[int] = 3
MAX_TRANSITION_DIFF_CHARS: Final[int] = 65_536

def render_unified_diff(predecessor: EvidenceItem, current: EvidenceItem) -> str:
    ...
```

Implementation must use the standard library only:

```python
lines = difflib.unified_diff(
    predecessor.content.splitlines(),
    current.content.splitlines(),
    fromfile=f"evidence:{predecessor.evidence_id}",
    tofile=f"evidence:{current.evidence_id}",
    n=DIFF_CONTEXT_LINES,
    lineterm="",
)
rendered = "\n".join(lines)
```

If `len(rendered) > MAX_TRANSITION_DIFF_CHARS`, raise:

```text
ContextUnsupported("UNSUPPORTED_TRANSITION_DIFF: rendered diff ... exceeds 65536 characters")
```

Never truncate.

### 4.4 RED tests

Tests must prove:

- [ ] constants equal exactly `3` and `65_536`;
- [ ] exact header labels are `--- evidence:EV-old` / `+++ evidence:EV-new`;
- [ ] exactly three unchanged lines surround a single changed hunk when available;
- [ ] same inputs produce byte-identical output on repeated calls;
- [ ] two identical content bodies yield the deterministic empty string, not a summary;
- [ ] a result of exactly 65,536 characters is allowed;
- [ ] 65,537 characters is refused with `ContextUnsupported` and no truncation;
- [ ] no semantic labels (`CORRECTION`, `SUPPORT`, `CONFLICT`, `NEW`) are inserted by the helper;
- [ ] predecessor/current `EvidenceItem` objects are not mutated.

For the exact boundary tests, monkeypatch `difflib.unified_diff` to return deterministic line sequences whose joined output length is controlled; do not allocate giant semantic fixtures unnecessarily.

Run RED:

```bash
uv run pytest -q tests/unit/test_contrastive_diff.py
```

Expected: missing module.

### 4.5 GREEN

Implement only the contract above.

Run:

```bash
uv run pytest -q tests/unit/test_contrastive_diff.py
uv run ruff check src/foundry/application/context_errors.py src/foundry/application/contrastive_diff.py tests/unit/test_contrastive_diff.py
uv run mypy src/foundry/application/context_errors.py src/foundry/application/contrastive_diff.py
```

- [ ] Commit:

```bash
git add src/foundry/application/context_errors.py src/foundry/application/contrastive_diff.py tests/unit/test_contrastive_diff.py
git commit -m "feat: add bounded contrastive evidence diff"
```

---

## 5. Task T3 — Structural comparison-context compiler

**Commit:** `feat: compile structural semantic change context`

### 5.1 Files

Create:

- `src/foundry/application/contrastive_context.py`
- `tests/unit/test_contrastive_context.py`

### 5.2 Public interface

Export:

```python
MAX_COMPARISON_CONTEXT_CHARS: Final[int] = 131_072

def compile_comparison_context(
    *,
    delta: tuple[EvidenceItem, ...],
    state: IntentState,
    profile_address_ids: tuple[str, ...],
) -> ComparisonContext:
    ...

def comparison_context_json(context: ComparisonContext) -> str:
    ...

def comparison_context_character_count(context: ComparisonContext) -> int:
    ...

def contrastive_address_ids(context: ComparisonContext) -> tuple[str, ...]:
    ...

def historical_evidence_ids(context: ComparisonContext) -> tuple[str, ...]:
    ...
```

Canonical context JSON must be:

```python
json.dumps(
    context.model_dump(mode="json"),
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
)
```

The 131,072-character limit is measured on that exact string. It is a support limit, not a semantic threshold.

### 5.3 Locked algorithm

For each `current` evidence item in `delta`, in delta order:

1. If `current.supersedes_evidence_id is None`, create no transition capsule for it.
2. Else retrieve `predecessor = state.semantic.evidence[current.supersedes_evidence_id]`. Missing predecessor is a structural error (`ValueError`); there is no search fallback.
3. Require `current.artifact_ref == predecessor.artifact_ref`; mismatch is a structural error. Normal ingestion already enforces this, but the compiler is independently safe.
4. Derive `view = derive_view(state.semantic)` once.
5. A claim is transition-touched iff:
   - it is currently LIVE (its claim id appears in a current locus); and
   - `predecessor.evidence_id in view.effective_evidence[claim_id]`.
6. Sort touched claims by `claim_id`; touched addresses are the sorted unique `claim.address_id` values.
7. Create these exact structural edges:
   - `current --SUPERSEDES--> predecessor` once;
   - `predecessor --EFFECTIVE_EVIDENCE_OF--> claim` once per touched claim;
   - `claim --CLAIM_AT_ADDRESS--> address` once per touched claim.
8. `historical_diff = render_unified_diff(predecessor, current)`.
9. Create an `EvidenceTransitionContext` even when zero live claims are touched: the explicit lineage/diff is still structural context, with empty touched claim/address tuples.
10. Separately, for every LIVE claim at an address listed in `profile_address_ids`, add one sorted `address --ACTIVE_CLAIM_PROFILE--> claim` edge to `ComparisonContext.active_claim_profile_edges`.
11. Build the immutable `ComparisonContext`.
12. If `comparison_context_character_count(context) > 131_072`, raise `ContextUnsupported("UNSUPPORTED_COMPARISON_CONTEXT: ... exceeds 131072 characters")` before any provider can be called.

The compiler never reads address/claim text to select an object. The only selection inputs are ids, active-liveness, explicit evidence lineage, effective-evidence membership, and caller-supplied profile address ids.

### 5.4 RED tests

Build real `IntentState`/`SemanticState` fixtures or a real in-memory governor where useful. Prove:

- [ ] direct dependency: claim cites predecessor in its immutable `evidence_ids` -> touched;
- [ ] support dependency: predecessor appears only through an ACTIVE `SUPPORTS_CLAIM` record -> touched;
- [ ] inactive/superseded claim is not touched;
- [ ] evidence cited by an unrelated live claim is not touched if it is not the explicit predecessor;
- [ ] same words/descriptors with no lineage edge do not create a transition or touched claim;
- [ ] one current version touches multiple live claims deterministically and addresses deduplicate/sort;
- [ ] `ACTIVE_CLAIM_PROFILE` edges include all live claims at the explicitly supplied profile addresses and no claims at other addresses;
- [ ] transition edges exactly explain the path and contain no semantic classification;
- [ ] the historical diff contains predecessor bytes only through the deterministic diff; `ReasoningRequest.evidence` is not involved here;
- [ ] `historical_evidence_ids` returns predecessor ids only, sorted and deduplicated;
- [ ] `contrastive_address_ids` returns only structurally touched addresses;
- [ ] context size 131,072 allowed / 131,073 refused; no truncation/fallback;
- [ ] output independent of mapping insertion order.

Run RED:

```bash
uv run pytest -q tests/unit/test_contrastive_context.py
```

Expected: missing module.

### 5.5 GREEN

Implement exactly the algorithm above. Do not add retrieval abstractions, scoring, caches, persistent context records, or model calls.

Run:

```bash
uv run pytest -q tests/unit/test_comparison_context_contract.py tests/unit/test_contrastive_diff.py tests/unit/test_contrastive_context.py
uv run ruff check src/foundry/application/contrastive_context.py tests/unit/test_contrastive_context.py
uv run mypy src/foundry/application/contrastive_context.py
```

- [ ] Commit:

```bash
git add src/foundry/application/contrastive_context.py tests/unit/test_contrastive_context.py
git commit -m "feat: compile structural semantic change context"
```

---

## 6. Task T4 — Wire 9P2 context into the existing two-call assimilation loop

**Commit:** `feat: wire contrastive context into assimilation`

### 6.1 Files

Modify:

- `src/foundry/application/assimilation_context.py`
- `src/foundry/application/incremental_assimilation.py`
- `tests/unit/test_assimilation_context.py`
- `tests/unit/test_incremental_assimilation.py`

### 6.2 `assimilation_context.py`

Remove the local definition of `ContextUnsupported`; import it from `foundry.application.context_errors` so existing imports from `assimilation_context` continue to work through the imported name.

Keep:

```python
CANDIDATE_ADDRESS_THRESHOLD = 200
ASSIMILATION_JUDGMENT_KINDS = {BIND_TO_ADDRESS, CREATE_ADDRESS}
CLAIM_ASSIMILATION_JUDGMENT_KINDS = {SUPPORTS_CLAIM, ASSERT_CLAIM, SUPERSEDE, CONFLICTS_WITH}
```

Add a public pure helper:

```python
def live_claims_at(
    state: IntentState, address_ids: frozenset[str]
) -> tuple[SemanticClaim, ...]:
    # active ASSERT claims only; sorted by claim_id
```

#### Call 1

`assemble_assimilation_request(...)` must:

1. compute active in-scope addresses exactly as today;
2. reject >200 exactly as today;
3. compute all live claims at those address ids;
4. compile comparison context with `profile_address_ids=tuple(address.address_id for address in addresses)`;
5. return:

```python
ReasoningRequest(
    project_id=project_id,
    evidence=delta,                         # current delta only, still citable
    known_addresses=addresses,
    known_claims=claims,                   # NEW in 9P2
    comparison_context=context,            # NEW in 9P2
    allowed_judgment_kinds=ASSIMILATION_JUDGMENT_KINDS,
)
```

The model seeing claims in Call 1 does not grant it claim operations: allowed kinds remain only BIND/CREATE and adapter enforcement remains structural.

#### Call 2

`assemble_claim_request(...)` retains `evidence=delta` exactly. Add no predecessor evidence to `request.evidence`.

It receives a `neighborhood` that has already been widened by the orchestrator (below), builds addresses/live claims for those ids, compiles a call-specific comparison context with those ids as `profile_address_ids`, and returns it on the request.

### 6.3 `incremental_assimilation.py`

Preserve `CALLS_PER_DELTA = 2`.

After Call 1:

```python
decision_neighborhood = neighborhood_from_decisions(governor.state(), decisions_1)
contrastive = contrastive_address_ids(request_1.comparison_context)
claim_neighborhood = tuple(sorted(set(decision_neighborhood) | set(contrastive)))
```

Use `claim_neighborhood` for Call 2. This is not a semantic match: `contrastive` comes only from the explicit predecessor -> effective-evidence -> live-claim structural path.

Extend `DeltaOutcome` with:

```python
claim_neighborhood: tuple[str, ...]
```

Keep existing `neighborhood` meaning unchanged: it is still the Call-1 applied CREATE/BIND decision neighbourhood. The new field makes the structurally widened Call-2 scope explicit and auditable.

No other outcome/state field changes.

### 6.4 Rewrite obsolete 9P assertions

The old tests explicitly say Call 1 sends no claims and persistent Call 2 rereads zero unchanged evidence. Those assertions are now intentionally obsolete.

Replace them with the 9P2 law:

> Current citable evidence remains delta-only; structurally selected predecessor material may appear only in non-citable `comparison_context`.

Do **not** simply delete coverage.

### 6.5 RED tests

Required tests across the two existing modules:

- [ ] Call 1 for a seeded address includes its live claim profile while allowed kinds remain exactly BIND/CREATE;
- [ ] Call 1 comparison context includes old->new transition when new delta supersedes evidence effectively supporting that claim;
- [ ] scope-B claims remain invisible to a scope-A Call 1;
- [ ] superseded/inactive claims remain invisible;
- [ ] 200-address request still works; 201 raises `ContextUnsupported` before reasoner invocation;
- [ ] Call 2 `request.evidence` contains only current delta (`EV-new`), never predecessor `EV-old`;
- [ ] Call 2 comparison context contains predecessor diff/id and old claim profile;
- [ ] when Call 1 returns BIND to existing A, `neighborhood == claim_neighborhood == (A,)`;
- [ ] when Call 1 intentionally CREATEs a new address even though the transition structurally touches old A, `neighborhood` contains the created address but `claim_neighborhood` contains both created address and old A; Call 2 therefore still sees the touched old claim;
- [ ] a genuinely unrelated new artifact with no predecessor creates no transition and does not widen Call 2;
- [ ] two reasoner calls exactly on success; no third call;
- [ ] any context-limit refusal happens before the relevant reasoner call and there is no retry/fallback.

Run RED after modifying tests but before production wiring:

```bash
uv run pytest -q tests/unit/test_assimilation_context.py tests/unit/test_incremental_assimilation.py
```

Expected: failures specifically because Call 1 lacks claims/context and Call 2 neighbourhood is not structurally widened.

### 6.6 GREEN

Implement the minimum wiring above.

Run:

```bash
uv run pytest -q \
  tests/unit/test_comparison_context_contract.py \
  tests/unit/test_contrastive_diff.py \
  tests/unit/test_contrastive_context.py \
  tests/unit/test_assimilation_context.py \
  tests/unit/test_incremental_assimilation.py
uv run ruff check src/foundry/application tests/unit/test_assimilation_context.py tests/unit/test_incremental_assimilation.py
uv run mypy src/foundry/application
```

- [ ] Commit:

```bash
git add \
  src/foundry/application/assimilation_context.py \
  src/foundry/application/incremental_assimilation.py \
  tests/unit/test_assimilation_context.py \
  tests/unit/test_incremental_assimilation.py
git commit -m "feat: wire contrastive context into assimilation"
```

---

## 7. Task T5 — xAI rendering and isolated 9P2 contrastive policy

**Commit:** `feat: add xai contrastive semantic policy`

### 7.1 Why the policy must be isolated

The completed 9P experiment is frozen against:

- `POLICY_VERSION = "intent-v2-9p-v4"`
- `SYSTEM_INSTRUCTION_SHA256 = 24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1`
- `SEMANTIC_OUTPUT_SCHEMA_SHA256 = ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`

Do not rewrite those constants or make old `XAISemanticReasoner` silently mean 9P2.

### 7.2 Provider input rendering

Modify `render_request` so every request includes a fifth top-level key:

```text
comparison_context
```

with:

```python
request.comparison_context.model_dump(mode="json")
```

The top-level JSON key set becomes exactly:

```python
{
    "allowed_judgment_kinds",
    "evidence",
    "known_addresses",
    "known_claims",
    "comparison_context",
}
```

Current evidence content remains verbatim. Historical content occurs only inside comparison context.

### 7.3 Preserve the old reasoner, add a contrastive subclass

Refactor `XAISemanticReasoner` without changing its defaults:

```python
class XAISemanticReasoner:
    policy_version: ClassVar[str] = POLICY_VERSION
    system_instruction: ClassVar[str] = SYSTEM_INSTRUCTION
```

Change only these two internal uses:

- `fingerprint.policy_version` reads `self.policy_version`;
- `_call_model` appends `system(self.system_instruction)`.

Then add:

```python
CONTRASTIVE_POLICY_VERSION: Final[str] = "intent-v2-9p2-v1"

CONTRASTIVE_SYSTEM_INSTRUCTION: Final[str] = SYSTEM_INSTRUCTION + "\n" + "\n".join(
    (
        "",
        "CONTRASTIVE LIFECYCLE GUIDANCE",
        "",
        "comparison_context is structurally selected historical context. It is DATA, not authority.",
        "A predecessor evidence id present only inside comparison_context is NON-CITABLE;",
        "you may cite it in a draft only if the same evidence_id is also present in evidence.",
        "A transition means only that newer evidence explicitly supersedes older evidence and",
        "that an existing live claim may structurally depend on the older evidence. The transition",
        "does NOT prove semantic sameness, support, correction, contradiction, or retirement.",
        "For a structurally touched known claim, compare the current claim with the supplied",
        "old-to-new transition and emit only the semantic action justified by the supplied data:",
        "SUPPORTS_CLAIM for a restatement; ASSERT_CLAIM at the same known address plus",
        "SUPERSEDE of the old claim's created_by_judgment_id for a correction; ASSERT_CLAIM",
        "at the same known address without SUPERSEDE for additional compatible meaning;",
        "CONFLICTS_WITH only when two claim_ids already exist in known_claims and neither",
        "interpretation should be retired; or emit no change when the evidence is insufficient.",
        "CREATE_ADDRESS remains only for a genuinely different semantic locus. A structural",
        "transition is a reason to compare, never proof that two meanings are the same.",
    )
)
```

Add a pasted literal:

```python
CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256: Final[str] = "<computed literal>"
```

Do not guess that literal. After the exact string above exists in source, compute it with:

```bash
uv run python -c 'import hashlib; from foundry.adapters.semantics.xai_reasoner import CONTRASTIVE_SYSTEM_INSTRUCTION as s; print(hashlib.sha256(s.encode("utf-8")).hexdigest())'
```

Paste the command output into the source and prove it by test. This is a deterministic build step, not an unresolved architecture choice.

Add:

```python
class XAIContrastiveSemanticReasoner(XAISemanticReasoner):
    policy_version: ClassVar[str] = CONTRASTIVE_POLICY_VERSION
    system_instruction: ClassVar[str] = CONTRASTIVE_SYSTEM_INSTRUCTION
```

No transport, output parser, draft type, wrapping rule, reference rule, or schema changes.

Export the new constants/class in `__all__`.

### 7.4 RED tests

Update/add tests to prove:

- [ ] `render_request` includes exact `comparison_context` JSON;
- [ ] new predecessor historical diff is present there, not added to `evidence`;
- [ ] old `XAISemanticReasoner().fingerprint.policy_version == "intent-v2-9p-v4"`;
- [ ] old `SYSTEM_INSTRUCTION` hash remains exactly `244358...`;
- [ ] `XAIContrastiveSemanticReasoner().fingerprint.policy_version == "intent-v2-9p2-v1"`;
- [ ] contrastive class sends `CONTRASTIVE_SYSTEM_INSTRUCTION` as its system message on fake transport;
- [ ] new pasted contrastive prompt hash equals a fresh sha256 of the exact bytes;
- [ ] `semantic_output_schema_sha256()` remains exactly `ffc6946a...` and no output draft field changed;
- [ ] historical predecessor is non-citable: build a request whose `evidence=(EV-new,)` while `comparison_context` names `EV-old`; return a fake `SupportsClaimDraft` or `AssertClaimDraft` citing `EV-old`; adapter raises `SemanticOutputError` for unknown evidence and returns no judgment;
- [ ] the same `EV-old` becomes citable only when it is explicitly added to `request.evidence` (control test; 9P2 normal assimilation does not do this);
- [ ] allowed-kind enforcement remains: Call 1 cannot emit ASSERT/SUPERSEDE merely because it sees known claims.

Keep the existing `test_xai_pair_contract.py::test_policy_version_bumped_for_the_pair_contract` passing unchanged; it protects historical 9P policy identity.

Run RED before production changes:

```bash
uv run pytest -q \
  tests/unit/test_xai_lifecycle_prompt.py \
  tests/unit/test_xai_lifecycle_drafts.py \
  tests/unit/test_xai_semantic_reasoner.py \
  tests/unit/test_xai_pair_contract.py \
  tests/unit/test_xai_decimal_contract.py
```

Expected: failures only for the new comparison-context/new contrastive-policy expectations.

### 7.5 GREEN

Implement rendering/class-policy changes. Recompute and paste the contrastive prompt hash using the exact command above.

Run:

```bash
uv run pytest -q \
  tests/unit/test_xai_lifecycle_prompt.py \
  tests/unit/test_xai_lifecycle_drafts.py \
  tests/unit/test_xai_semantic_reasoner.py \
  tests/unit/test_xai_pair_contract.py \
  tests/unit/test_xai_decimal_contract.py
uv run ruff check src/foundry/adapters/semantics/xai_reasoner.py tests/unit/test_xai_lifecycle_prompt.py tests/unit/test_xai_lifecycle_drafts.py tests/unit/test_xai_semantic_reasoner.py
uv run mypy src/foundry/adapters/semantics/xai_reasoner.py
```

- [ ] Commit:

```bash
git add \
  src/foundry/adapters/semantics/xai_reasoner.py \
  tests/unit/test_xai_lifecycle_prompt.py \
  tests/unit/test_xai_lifecycle_drafts.py \
  tests/unit/test_xai_semantic_reasoner.py
git commit -m "feat: add xai contrastive semantic policy"
```

---

## 8. Task T6 — Track A regression through the real governor

**Commit:** `test: prove Track A contrastive correction lifecycle`

### 8.1 File

Create `tests/unit/test_9p2_track_a_regression.py`.

Use the real `SemanticGovernor`, `InMemoryEventStore`, reducer/view/admission rules, and a scripted in-process reasoner. Block network sockets. Do not call xAI.

### 8.2 Fixture story

Use a small self-contained lifecycle derived from the failed 9P Track A, not the old live artifact ids.

T1:

1. Ingest `EV-A1`, artifact `docs/semantic-address.md`, with content containing the old interpretation: after admission, address equality is deterministic/authoritative.
2. Create one intent-engine address A with descriptors `SemanticAddress | identity vs descriptors`.
3. Assert old claim C-A1 at A from `EV-A1`; record its creating judgment id as `J-A1`.
4. Ingest separate `EV-N1`, create one constitution/control address N, and assert stable control claim `J-N1`.
5. Record derivation edges through `governor.derive`:

```text
D-A1 <- J-A1
D-A2 <- D-A1
D-A3 <- D-A2
D-N1 <- J-N1
D-N2 <- D-N1
```

Assert `view.stale_ids == ()` before T2.

T2:

Create `EV-A2` with the same artifact_ref, `supersedes_evidence_id="EV-A1"`, and content stating the corrected interpretation: identity is a deterministic referential fact under the current admitted interpretation, not eternal semantic truth, and the binding may be superseded.

Scripted reasoner behavior:

#### Call 1 assertions before returning BIND

The scripted callback must assert from its received `ReasoningRequest`:

- allowed kinds are exactly BIND/CREATE;
- A is in known addresses;
- C-A1 is in known claims;
- `EV-A2` is the sole citable delta evidence for the transition;
- comparison context contains `EV-A2 --SUPERSEDES--> EV-A1`;
- C-A1 is touched through `EV-A1 --EFFECTIVE_EVIDENCE_OF--> C-A1`;
- the deterministic diff includes the old/new changed lines;
- predecessor content is not present as another `request.evidence` item.

Then return one `BIND_TO_ADDRESS` judgment binding the T2 candidate to A. Do not CREATE another address.

#### Call 2 assertions and proposals

The callback must assert:

- allowed kinds are exactly SUPPORT/ASSERT/SUPERSEDE/CONFLICT;
- A and C-A1 remain visible;
- the same structural transition is visible;
- `request.evidence` is still `(EV-A2,)` only.

Return in one batch:

1. `ASSERT_CLAIM` at A with the corrected T2 interpretation, citing only `EV-A2`, model/inferred authority;
2. `SUPERSEDE(target_judgment_id="J-A1")` with reason that the T2 interpretation corrects the old current interpretation.

Expected deterministic admission:

- new ASSERT is low-risk/APPLY and creates C-A2;
- model SUPERSEDE is material and remains pending (`REQUIRE_SECOND_LENS` under current policy); old C-A1 is still live until authority.

### 8.3 Authority step

After `assimilate_delta` returns:

1. Record one project-wide `AuthorityRecord` for `human://architect` through `governor.record_authority`.
2. Submit one human `SemanticJudgment` with the exact same `SupersedeProposal` target/reason as the pending model proposal and fingerprint `provider="human", model="human://architect"`, passing `human_actor_id="human://architect"`.
3. Expect `AdmissionRoute.APPLY` via human authority.

### 8.4 Final regression assertions

Prove all of these:

- [ ] exactly two scripted reasoner calls occurred;
- [ ] no second Track-A semantic address was created; only A plus the unrelated control address exist;
- [ ] A's current locus contains C-A2 and not C-A1 after human supersession;
- [ ] C-A1 and its judgment remain readable historically;
- [ ] `view.stale_ids` contains `D-A1`, `D-A2`, `D-A3`;
- [ ] `D-N1`, `D-N2` are not stale;
- [ ] pending model supersession is `SATISFIED_BY` or otherwise no longer unresolved according to the existing derived-governance rule after the matching human apply;
- [ ] no `EQUIVALENT`, `DISTINCT`, or new judgment kind is involved;
- [ ] no predecessor evidence id is cited by the T2 new claim;
- [ ] two calls, not three;
- [ ] replay of the in-memory ledger reproduces the same semantic view/state using the existing replay path.

This is a regression of the known failure, **not** scientific proof of 9P2.

### 8.5 RED -> GREEN

Create the full test first and run:

```bash
uv run pytest -q tests/unit/test_9p2_track_a_regression.py
```

Expected RED: missing comparison-context behavior or incorrect request wiring until T1-T5 are present. If it unexpectedly passes before the intended assertions exist, the test is insufficient.

Implement no new production feature in T6 unless a tiny bug fix is required by the already-approved T1-T5 contracts. Any architecturally material missing behavior is an `ARCHITECTURE QUESTION`, not permission to expand scope.

Run GREEN:

```bash
uv run pytest -q \
  tests/unit/test_9p2_track_a_regression.py \
  tests/unit/test_longitudinal_derivations.py \
  tests/unit/test_semantic_view.py \
  tests/unit/test_admission.py
```

- [ ] Commit:

```bash
git add tests/unit/test_9p2_track_a_regression.py
git commit -m "test: prove Track A contrastive correction lifecycle"
```

If T6 requires a production bug fix within the approved contracts, commit that fix separately before the regression-test commit, with its own RED/GREEN evidence.

---

## 9. Task T7 — Full verification and architecture gate

No live calls. Do not create experiment artifacts yet.

### 9.1 Focused suite

- [ ] Run:

```bash
uv run pytest -q \
  tests/unit/test_comparison_context_contract.py \
  tests/unit/test_contrastive_diff.py \
  tests/unit/test_contrastive_context.py \
  tests/unit/test_assimilation_context.py \
  tests/unit/test_incremental_assimilation.py \
  tests/unit/test_xai_lifecycle_prompt.py \
  tests/unit/test_xai_lifecycle_drafts.py \
  tests/unit/test_xai_semantic_reasoner.py \
  tests/unit/test_xai_pair_contract.py \
  tests/unit/test_xai_decimal_contract.py \
  tests/unit/test_9p2_track_a_regression.py
```

Expected: all pass, zero network.

### 9.2 Full repository verification

- [ ] Run fresh, in this order:

```bash
uv run pytest -v
uv run ruff check .
uv run mypy src
git diff --check
git status --short
```

Expected:

- pytest: 0 failed;
- ruff: 0 errors;
- mypy: 0 errors;
- diff check: no whitespace errors;
- status: clean after all task commits.

### 9.3 Explicit architecture checks

- [ ] Prove `CALLS_PER_DELTA == 2`.
- [ ] Prove `CANDIDATE_ADDRESS_THRESHOLD == 200`.
- [ ] Prove `DIFF_CONTEXT_LINES == 3`.
- [ ] Prove `MAX_TRANSITION_DIFF_CHARS == 65_536`.
- [ ] Prove `MAX_COMPARISON_CONTEXT_CHARS == 131_072`.
- [ ] Prove `POLICY_VERSION == "intent-v2-9p-v4"` for historical `XAISemanticReasoner`.
- [ ] Prove contrastive policy version is `intent-v2-9p2-v1`.
- [ ] Prove old system prompt hash remains `24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1`.
- [ ] Prove contrastive prompt pasted hash equals fresh bytes.
- [ ] Prove output schema hash remains `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`.
- [ ] Prove no new `JudgmentKind` was added.
- [ ] Prove no new event type or `SemanticState` field was added for comparison context.
- [ ] Prove old 9P experiment directory is byte-unchanged from the implementation-plan starting commit.
- [ ] Prove production selection code contains no lexical similarity, embedding call, fuzzy matcher, semantic score, LLM diff, or full-history fallback.
- [ ] Prove Track C/T3 observation coverage was not silently claimed/fixed by this milestone.

Use `git diff <implementation-start-sha>...HEAD -- <path>` and source inspection as evidence, not assertions based on memory.

### 9.4 Review gate

Use `superpowers:requesting-code-review` on the full implementation diff. Review specifically for:

1. any deterministic semantic conclusion leaking into the compiler;
2. any historical evidence becoming citable through comparison context;
3. any unbounded context path;
4. any third reasoner call or retry;
5. mutation of old 9P policy/artifacts;
6. output-schema drift;
7. divergence between assembler tests and actual orchestrator flow.

Fix Critical/Important findings with RED/GREEN and re-run all verification. Do not waive them.

### 9.5 Completion report

Report:

- implementation starting SHA;
- every task commit SHA/message;
- exact changed files;
- tests added/modified;
- focused and full verification commands with pass counts;
- ruff/mypy results;
- old 9P prompt/policy/schema identities;
- new contrastive prompt/policy identity;
- proof no live calls occurred;
- proof old 9P experiment artifacts were untouched;
- architecture-review result;
- clean `git status --short`.

Do **not** call the scientific 9P2 hypothesis passed at this point. The only allowed conclusion is that the implementation contract and known Track A regression are locally verified.

---

## 10. Post-plan scientific-validation gate — intentionally separate

After T7 is accepted by the architect, stop implementation.

The next architecture/planning step is a **separate preregistered 9P2 validation experiment**. It must be designed only after the implementation is frozen, but its unseen lifecycle fixture, expectations, adjudication rules, token/context metrics, call/cost ceilings, provider policy hash, and stop-on-failure rules must be sealed **before the first live provider call**.

Track A may appear only as a regression/control. It cannot count as new scientific evidence because 9P2 was designed from that failure.

The unseen experiment must determine at minimum:

1. semantic continuity correctness on a lifecycle not used to design 9P2;
2. no duplicate semantic identity for the tracked changed locus;
3. correct support vs correction behavior under governed supersession;
4. persistent context remains materially smaller than reconstruction;
5. every rehydrated historical byte has a structural inclusion reason;
6. replay/governance integrity remains intact;
7. no deterministic semantic authority has entered the compiler.

9Q cross-model inheritance remains unauthorized until that separate experiment passes or the architect explicitly revises the gate.
