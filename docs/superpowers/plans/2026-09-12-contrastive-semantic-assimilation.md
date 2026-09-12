# 9P2 Contrastive Semantic Assimilation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved 9P2 Contrastive Semantic Context Compiler v0 and prove locally that structurally rehydrated history fixes the known Track A semantic-correction failure without adding deterministic semantic authority, a third model call, or whole-history reconstruction.

**Architecture:** Preserve the existing two-call semantic assimilation loop. Extend `ReasoningRequest` with provider-neutral ephemeral comparison context; compile that context only from explicit evidence lineage and current effective-evidence edges; render deterministic bounded unified diffs; give Call 1 active claim profiles; give Call 2 both the Call-1 decision neighbourhood and structurally touched existing addresses. AI continues to decide meaning. Foundry decides only what structurally connected history is shown and whether the request is within support bounds.

**Tech Stack:** Python 3.12, Pydantic v2 frozen models, standard-library `difflib`, existing event-sourced semantic governor/state, pytest, ruff, mypy, xAI adapter with fake transport only in this plan.

**Spec:** `docs/superpowers/specs/2026-09-12-contrastive-semantic-assimilation-design.md`

**Approved design base:** `02ffde24826e12bec726a1e21606861e08bdbaf7`

**Runtime rule:** ZERO live provider/model/judge calls in this plan. The unseen scientific 9P2 experiment is a later preregistered plan after this implementation is frozen and locally verified.

---

## 0. Global constraints

1. `FOUNDRY_CONSTITUTION.md` and the approved 9P2 spec outrank this plan. If an architecturally material ambiguity appears, stop and report `ARCHITECTURE QUESTION:`.
2. **AI understands meaning; Foundry governs meaning.** Production code may follow structural edges, but may not classify a transition as support, correction, conflict, or new meaning.
3. No embeddings, lexical similarity, descriptor equality, fuzzy matching, semantic score, heuristic hunk selection, source-name ranking, or semantic top-K.
4. No whole-history fallback. Unsupported context fails explicitly before a provider call. No truncation or summarization.
5. Historical comparison material is non-citable. Only ids in `ReasoningRequest.evidence` are admissible evidence references in model drafts.
6. Exactly two frontier calls per successful delta. No reconciliation, classification, repair, or retry call.
7. No new durable `JudgmentKind`, event type, reducer mutation, semantic-state field, or persistence table for 9P2 context.
8. `ComparisonContext` is request-only. Claims and addresses remain immutable; corrections remain `ASSERT_CLAIM(new at same address) + SUPERSEDE(old creating judgment)` under existing governance.
9. Active in-scope address support limit stays exactly 200; 201 fails before a provider call. No fallback retrieval branch.
10. Per-transition rendered diff limit: exactly 65,536 Unicode characters. Total canonical rendered comparison-context limit per request: exactly 131,072 Unicode characters.
11. Unified diff: line based, `difflib.unified_diff`, exactly three unchanged context lines per hunk, evidence-id labels, deterministic output.
12. Do not modify `docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/**`.
13. Preserve historical 9P xAI identity: `POLICY_VERSION == "intent-v2-9p-v4"`, `SYSTEM_INSTRUCTION_SHA256 == "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1"`, and `SEMANTIC_OUTPUT_SCHEMA_SHA256 == "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"` for `XAISemanticReasoner`.
14. 9P2 gets a distinct xAI contrastive policy/class. Do not silently repurpose the historical 9P class or prompt.
15. Provider output schema remains unchanged; 9P2 changes input context/guidance only.
16. Strict TDD per task: intended RED -> minimum GREEN -> verification -> commit. Never weaken a valid invariant test to get green.
17. Tests that touch provider adapters must block sockets. No network is permitted.
18. One bounded task at a time. Do not pre-implement later tasks.

---

## 1. File map

| Path | Change | Task |
|---|---|---|
| `src/foundry/ports/semantic_reasoner.py` | MODIFY — provider-neutral comparison-context contract | T1 |
| `tests/unit/test_comparison_context_contract.py` | NEW | T1 |
| `src/foundry/application/context_errors.py` | NEW — bounded-context refusal | T2 |
| `src/foundry/application/contrastive_diff.py` | NEW — deterministic bounded unified diff | T2 |
| `tests/unit/test_contrastive_diff.py` | NEW | T2 |
| `src/foundry/application/contrastive_context.py` | NEW — structural comparison compiler | T3 |
| `tests/unit/test_contrastive_context.py` | NEW | T3 |
| `src/foundry/application/assimilation_context.py` | MODIFY — Call 1 claim profiles/context; Call 2 contrastive context | T4 |
| `src/foundry/application/incremental_assimilation.py` | MODIFY — structurally widen Call 2 claim neighbourhood | T4 |
| `tests/unit/test_assimilation_context.py` | MODIFY | T4 |
| `tests/unit/test_incremental_assimilation.py` | MODIFY | T4 |
| `src/foundry/adapters/semantics/xai_reasoner.py` | MODIFY — opt-in comparison rendering + isolated 9P2 policy/class | T5 |
| `tests/unit/test_xai_lifecycle_prompt.py` | MODIFY | T5 |
| `tests/unit/test_xai_lifecycle_drafts.py` | MODIFY | T5 |
| `tests/unit/test_xai_semantic_reasoner.py` | MODIFY | T5 |
| `tests/unit/test_9p2_track_a_regression.py` | NEW — real-governor Track A lifecycle | T6 |

Do not change semantic domain models, admission rules, reducer semantics, old experiment artifacts, or persistence adapters to make this milestone pass.

---

## 2. Task T0 — Isolated workspace and baseline

No code change and no commit.

- [ ] Read the constitution, `AGENTS.md`, approved 9P2 spec, and this plan.
- [ ] Use `superpowers:using-git-worktrees` to create an isolated worktree from the branch tip containing this plan.
- [ ] Verify:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected: intended 9P2 worktree and an empty status.

- [ ] Run the pre-change baseline:

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

Expected: PASS. If baseline fails, stop and use `superpowers:systematic-debugging` before 9P2 work.

---

## 3. Task T1 — Provider-neutral comparison-context contract

**Commit:** `feat: add contrastive reasoning context contract`

### Files

- NEW `tests/unit/test_comparison_context_contract.py`
- MODIFY `src/foundry/ports/semantic_reasoner.py`

### RED contract

Write tests first for these exact provider-neutral models:

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

Extend `ReasoningRequest` with exactly:

```python
comparison_context: ComparisonContext = Field(default_factory=ComparisonContext)
```

Tests must prove:

- [ ] default request gets an empty `ComparisonContext`, preserving existing callers;
- [ ] new models are frozen and reject extra fields via `FrozenModel`;
- [ ] blank ids and blank `artifact_ref` fail;
- [ ] `historical_diff=""` is legal;
- [ ] transition `inclusion_edges` cannot be empty;
- [ ] serialization is provider-neutral deterministic Pydantic data;
- [ ] contract contains no `classification`, `correction`, `supports`, `confidence`, `authority`, or `verdict` field.

Run RED:

```bash
uv run pytest -q tests/unit/test_comparison_context_contract.py
```

Expected: import/collection failure because the types do not exist.

### GREEN

Add the models in `ports/semantic_reasoner.py` before `ReasoningRequest`; import `StrEnum`; keep `SemanticReasoner` protocol unchanged. Document comparison context as request-only structural history, never evidence or semantic authority.

Run:

```bash
uv run pytest -q tests/unit/test_comparison_context_contract.py tests/unit/test_xai_semantic_reasoner.py
uv run mypy src/foundry/ports/semantic_reasoner.py
```

- [ ] Commit:

```bash
git add src/foundry/ports/semantic_reasoner.py tests/unit/test_comparison_context_contract.py
git commit -m "feat: add contrastive reasoning context contract"
```

---

## 4. Task T2 — Deterministic bounded old-to-new diff

**Commit:** `feat: add bounded contrastive evidence diff`

### Files

- NEW `src/foundry/application/context_errors.py`
- NEW `src/foundry/application/contrastive_diff.py`
- NEW `tests/unit/test_contrastive_diff.py`

### Contract

`context_errors.py` contains only:

```python
class ContextUnsupported(RuntimeError):
    """The exact structurally selected context exceeds a locked support bound."""
```

`contrastive_diff.py` exports:

```python
DIFF_CONTEXT_LINES: Final[int] = 3
MAX_TRANSITION_DIFF_CHARS: Final[int] = 65_536
```

and `render_unified_diff(predecessor: EvidenceItem, current: EvidenceItem) -> str` implemented exactly from the standard library shape below:

```python
def render_unified_diff(predecessor: EvidenceItem, current: EvidenceItem) -> str:
    lines = difflib.unified_diff(
        predecessor.content.splitlines(),
        current.content.splitlines(),
        fromfile=f"evidence:{predecessor.evidence_id}",
        tofile=f"evidence:{current.evidence_id}",
        n=DIFF_CONTEXT_LINES,
        lineterm="",
    )
    rendered = "\n".join(lines)
    if len(rendered) > MAX_TRANSITION_DIFF_CHARS:
        raise ContextUnsupported(
            "UNSUPPORTED_TRANSITION_DIFF: rendered diff "
            f"has {len(rendered)} characters; maximum is {MAX_TRANSITION_DIFF_CHARS}"
        )
    return rendered
```

No normalization, semantic filtering, hunk ranking, truncation, or model call.

### RED tests

Prove:

- [ ] constants are exactly 3 and 65,536;
- [ ] headers are exactly `--- evidence:EV-old` and `+++ evidence:EV-new`;
- [ ] three context lines per hunk when available;
- [ ] deterministic repeat output;
- [ ] identical old/new content returns `""`;
- [ ] exactly 65,536 chars allowed and 65,537 refused; use monkeypatch on `difflib.unified_diff` to control output size;
- [ ] no semantic labels are added;
- [ ] evidence objects are not mutated.

Run RED then GREEN:

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

### Files

- NEW `src/foundry/application/contrastive_context.py`
- NEW `tests/unit/test_contrastive_context.py`

### Public interface

Add exactly these public names:

- `MAX_COMPARISON_CONTEXT_CHARS: Final[int] = 131_072`
- `compile_comparison_context(*, delta: tuple[EvidenceItem, ...], state: IntentState, profile_address_ids: tuple[str, ...]) -> ComparisonContext`
- `comparison_context_json(context: ComparisonContext) -> str`
- `comparison_context_character_count(context: ComparisonContext) -> int`
- `contrastive_address_ids(context: ComparisonContext) -> tuple[str, ...]`
- `historical_evidence_ids(context: ComparisonContext) -> tuple[str, ...]`

Canonical context JSON is exactly:

```python
json.dumps(
    context.model_dump(mode="json"),
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
)
```

The 131,072 limit applies to `len()` of that exact string.

### Locked algorithm

For each current delta item, in delta order:

1. No `supersedes_evidence_id` -> no transition capsule.
2. Otherwise retrieve the predecessor by exact id from `state.semantic.evidence`; missing predecessor -> `ValueError`; no search.
3. Require the predecessor/current `artifact_ref` values to match; mismatch -> `ValueError`.
4. Derive one `CurrentSemanticView` using `derive_view(state.semantic)`.
5. A claim is transition-touched iff it is currently live and the predecessor id is present in `view.effective_evidence[claim_id]`.
6. Sort touched claims by id and touched addresses by unique `claim.address_id`.
7. Add one `current --SUPERSEDES--> predecessor` edge.
8. For every touched claim add `predecessor --EFFECTIVE_EVIDENCE_OF--> claim` and `claim --CLAIM_AT_ADDRESS--> address`.
9. Render the deterministic diff with T2.
10. Create a transition even with zero touched claims; explicit version lineage still exists.
11. For every live claim whose address is in caller-supplied `profile_address_ids`, add one sorted `address --ACTIVE_CLAIM_PROFILE--> claim` edge.
12. Build immutable `ComparisonContext`; if its canonical JSON length exceeds 131,072, raise `ContextUnsupported` with prefix `UNSUPPORTED_COMPARISON_CONTEXT`; never truncate/fallback.

Selection must not inspect claim/address wording to decide relevance.

### RED tests

Prove:

- [ ] direct immutable claim evidence dependency touches the claim;
- [ ] ACTIVE `SUPPORTS_CLAIM` effective evidence dependency touches the claim;
- [ ] superseded/inactive claim is excluded;
- [ ] unrelated evidence/claim is excluded;
- [ ] same wording with no explicit lineage edge does not create a touch;
- [ ] multiple touched claims sort deterministically and addresses deduplicate;
- [ ] active profile edges include only live claims at explicitly supplied profile addresses;
- [ ] transition edges are exactly structural and contain no semantic classification;
- [ ] historical ids helper returns predecessor ids only;
- [ ] contrastive address helper returns touched addresses only;
- [ ] 131,072 chars allowed / 131,073 refused, no truncation;
- [ ] mapping insertion order does not alter output.

Run:

```bash
uv run pytest -q tests/unit/test_contrastive_context.py
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

## 6. Task T4 — Wire 9P2 into the two-call assimilation loop

**Commit:** `feat: wire contrastive context into assimilation`

### Files

- MODIFY `src/foundry/application/assimilation_context.py`
- MODIFY `src/foundry/application/incremental_assimilation.py`
- MODIFY `tests/unit/test_assimilation_context.py`
- MODIFY `tests/unit/test_incremental_assimilation.py`

### `assimilation_context.py`

- Remove the local `ContextUnsupported`; import it from `context_errors` so existing imports from this module keep working.
- Keep `CANDIDATE_ADDRESS_THRESHOLD = 200` and both allowed-kind sets unchanged.
- Rename/promote `_live_claims_at` to public `live_claims_at(state, address_ids)`; active ASSERT claims only, sorted by claim id.

Call 1 must:

1. select every active in-scope address exactly as before;
2. reject count >200 before reasoner invocation;
3. include every live claim at those addresses in `known_claims`;
4. compile comparison context using those address ids as `profile_address_ids`;
5. keep `evidence=delta` and allowed kinds exactly BIND/CREATE.

Call 2 must:

1. keep `evidence=delta` exactly; predecessor evidence must not be inserted;
2. receive the already-widened `neighborhood` from the orchestrator;
3. include live claims at those addresses;
4. compile call-specific comparison context with those addresses as profile addresses;
5. keep allowed kinds exactly SUPPORT/ASSERT/SUPERSEDE/CONFLICT.

### `incremental_assimilation.py`

Keep `CALLS_PER_DELTA = 2`.

Immediately after Call 1:

```python
decision_neighborhood = neighborhood_from_decisions(governor.state(), decisions_1)
contrastive = contrastive_address_ids(request_1.comparison_context)
claim_neighborhood = tuple(sorted(set(decision_neighborhood) | set(contrastive)))
```

Use `claim_neighborhood` for Call 2. Extend `DeltaOutcome` with exactly:

```python
claim_neighborhood: tuple[str, ...]
```

Keep existing `neighborhood` semantics unchanged: Call-1 applied CREATE/BIND addresses only.

### Rewrite obsolete 9P tests, do not delete coverage

Replace the old rule “Call 1 has no claims / zero historical reread” with:

> Current citable evidence remains delta-only; structurally selected predecessor material may appear only in non-citable comparison context.

### RED tests

Prove:

- [ ] Call 1 includes active claims while allowed kinds stay BIND/CREATE;
- [ ] Call 1 contains transition context when new evidence supersedes effective evidence of a live claim;
- [ ] scope-B and inactive claims remain absent from scope-A Call 1;
- [ ] 200 addresses works, 201 raises before reasoner invocation;
- [ ] Call 2 `request.evidence` contains only current delta, never predecessor;
- [ ] Call 2 context contains predecessor id/diff and old current claim;
- [ ] BIND existing A -> `neighborhood == claim_neighborhood == (A,)`;
- [ ] deliberate Call-1 CREATE while old A is structurally touched -> `neighborhood` contains the new address, while `claim_neighborhood` contains both new address and old A so Call 2 still sees old A;
- [ ] unrelated new artifact with no predecessor does not widen Call 2;
- [ ] exactly two reasoner calls on success;
- [ ] any context-limit refusal happens before the relevant reasoner call, with no retry/fallback.

Run intended RED before production wiring, then GREEN:

```bash
uv run pytest -q tests/unit/test_assimilation_context.py tests/unit/test_incremental_assimilation.py
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
git add src/foundry/application/assimilation_context.py \
  src/foundry/application/incremental_assimilation.py \
  tests/unit/test_assimilation_context.py \
  tests/unit/test_incremental_assimilation.py
git commit -m "feat: wire contrastive context into assimilation"
```

---

## 7. Task T5 — xAI opt-in rendering and isolated 9P2 contrastive policy

**Commit:** `feat: add xai contrastive semantic policy`

### Files

- MODIFY `src/foundry/adapters/semantics/xai_reasoner.py`
- MODIFY `tests/unit/test_xai_lifecycle_prompt.py`
- MODIFY `tests/unit/test_xai_lifecycle_drafts.py`
- MODIFY `tests/unit/test_xai_semantic_reasoner.py`

### Preserve historical 9P behavior

Do not change old `POLICY_VERSION`, `SYSTEM_INSTRUCTION`, its pasted hash, or output-schema hash.

Change `render_request` signature to:

```python
def render_request(
    request: ReasoningRequest, *, include_comparison_context: bool = False
) -> str:
```

Build the existing four-key payload exactly as before. Add `"comparison_context": request.comparison_context.model_dump(mode="json")` **only when** `include_comparison_context is True`.

This makes old direct calls and historical `XAISemanticReasoner` rendering unchanged while the new 9P2 class opts in.

Refactor base class with exact class variables:

```python
class XAISemanticReasoner:
    policy_version: ClassVar[str] = POLICY_VERSION
    system_instruction: ClassVar[str] = SYSTEM_INSTRUCTION
    include_comparison_context: ClassVar[bool] = False
```

`fingerprint` reads `self.policy_version`. `_call_model` uses `self.system_instruction` and calls:

```python
render_request(
    request,
    include_comparison_context=self.include_comparison_context,
)
```

### Exact 9P2 policy text

Add:

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

Add a pasted `CONTRASTIVE_SYSTEM_INSTRUCTION_SHA256: Final[str]` whose value is the exact 64-hex output of this command after the source string above exists:

```bash
uv run python -c 'import hashlib; from foundry.adapters.semantics.xai_reasoner import CONTRASTIVE_SYSTEM_INSTRUCTION as s; print(hashlib.sha256(s.encode("utf-8")).hexdigest())'
```

The implementation must paste that command output literally and test it against a fresh hash. Do not compute the constant at import time and do not change the prompt after the hash is pasted.

Add:

```python
class XAIContrastiveSemanticReasoner(XAISemanticReasoner):
    policy_version: ClassVar[str] = CONTRASTIVE_POLICY_VERSION
    system_instruction: ClassVar[str] = CONTRASTIVE_SYSTEM_INSTRUCTION
    include_comparison_context: ClassVar[bool] = True
```

No transport, parser, draft model, reference rule, or output-schema change. Export the new class/constants in `__all__`.

### RED tests

Prove:

- [ ] default `render_request(request)` still has exactly the historical four top-level keys and omits comparison context;
- [ ] `render_request(request, include_comparison_context=True)` has exactly the five keys and exact comparison-context JSON;
- [ ] predecessor diff/id is not inserted into `evidence`;
- [ ] old base reasoner fingerprint remains `intent-v2-9p-v4` and sends historical system instruction;
- [ ] contrastive reasoner fingerprint is `intent-v2-9p2-v1`, sends contrastive instruction, and opts in to comparison rendering;
- [ ] historical system hash remains exact;
- [ ] new pasted contrastive hash equals fresh sha256 bytes;
- [ ] output-schema hash remains exact `ffc6946a...`;
- [ ] predecessor id present only in comparison context is non-citable: a fake SUPPORT/ASSERT draft citing it raises `SemanticOutputError` and yields no judgment;
- [ ] control: the same id is citable only if explicitly present in `request.evidence`;
- [ ] Call-1 allowed-kind enforcement still refuses ASSERT/SUPERSEDE even though known claims are visible.

Keep `test_xai_pair_contract.py::test_policy_version_bumped_for_the_pair_contract` green unchanged.

Run RED then GREEN:

```bash
uv run pytest -q \
  tests/unit/test_xai_lifecycle_prompt.py \
  tests/unit/test_xai_lifecycle_drafts.py \
  tests/unit/test_xai_semantic_reasoner.py \
  tests/unit/test_xai_pair_contract.py \
  tests/unit/test_xai_decimal_contract.py
uv run ruff check src/foundry/adapters/semantics/xai_reasoner.py \
  tests/unit/test_xai_lifecycle_prompt.py \
  tests/unit/test_xai_lifecycle_drafts.py \
  tests/unit/test_xai_semantic_reasoner.py
uv run mypy src/foundry/adapters/semantics/xai_reasoner.py
```

- [ ] Commit:

```bash
git add src/foundry/adapters/semantics/xai_reasoner.py \
  tests/unit/test_xai_lifecycle_prompt.py \
  tests/unit/test_xai_lifecycle_drafts.py \
  tests/unit/test_xai_semantic_reasoner.py
git commit -m "feat: add xai contrastive semantic policy"
```

---

## 8. Task T6 — Track A regression through the real governor

**Commit:** `test: prove Track A contrastive correction lifecycle`

### File

- NEW `tests/unit/test_9p2_track_a_regression.py`

Use `SemanticGovernor`, `InMemoryEventStore`, real reducer/view/admission, and a scripted in-process reasoner. Block sockets. No xAI call.

### T1 fixture

1. Ingest `EV-A1`, artifact `docs/semantic-address.md`, with old interpretation text: after admission, address equality is deterministic/authoritative.
2. Create one intent-engine address A with descriptors `SemanticAddress | identity vs descriptors`.
3. Assert old claim C-A1 at A from `EV-A1`; its creating judgment id is `J-A1`.
4. Ingest `EV-N1`, create a separate constitution/control address N, and assert stable control claim `J-N1`.
5. Record derivations with `governor.derive`:

```text
D-A1 <- J-A1
D-A2 <- D-A1
D-A3 <- D-A2
D-N1 <- J-N1
D-N2 <- D-N1
```

Assert no stale ids before T2.

### T2 fixture

Create `EV-A2` with the same `artifact_ref`, `supersedes_evidence_id="EV-A1"`, and corrected text: identity is a deterministic referential fact under the current admitted interpretation, not eternal semantic truth, and the binding may later be superseded.

Scripted Call 1 callback must inspect its real `ReasoningRequest` and assert:

- BIND/CREATE only;
- A visible;
- C-A1 visible;
- `request.evidence == (EV-A2,)`;
- comparison path `EV-A2 --SUPERSEDES--> EV-A1 --EFFECTIVE_EVIDENCE_OF--> C-A1 --CLAIM_AT_ADDRESS--> A`;
- deterministic old/new diff contains both changed interpretations;
- EV-A1 is not a second citable evidence item.

Then return one `BIND_TO_ADDRESS` to A; no CREATE.

Scripted Call 2 callback must assert A/C-A1 and the same transition remain visible while `request.evidence == (EV-A2,)`. Return one batch:

1. `ASSERT_CLAIM` corrected interpretation at A citing only EV-A2 with inferred/model authority;
2. `SUPERSEDE(target_judgment_id="J-A1")` with a correction reason.

Expected existing admission: ASSERT APPLY; model SUPERSEDE held as material; old claim remains live until authority.

### Human authority

After `assimilate_delta`:

1. record a project-wide `AuthorityRecord` for `human://architect` using `governor.record_authority`;
2. submit a human `SemanticJudgment` containing the identical `SupersedeProposal` target/reason with fingerprint `provider="human", model="human://architect"` and `human_actor_id="human://architect"`;
3. expect `AdmissionRoute.APPLY`.

### Final assertions

- [ ] exactly two scripted reasoner calls;
- [ ] no duplicate Track-A address; durable addresses are A plus control N only;
- [ ] A current locus contains new C-A2 and not old C-A1 after authority;
- [ ] old claim/judgment remain historically readable;
- [ ] stale ids contain D-A1/D-A2/D-A3;
- [ ] D-N1/D-N2 remain clean;
- [ ] pending model supersession is satisfied/no longer unresolved under existing derived-governance rules;
- [ ] no EQUIVALENT/DISTINCT/new judgment kind;
- [ ] new claim cites EV-A2 only, never predecessor EV-A1;
- [ ] replay reproduces final semantic state/view.

This is a regression of the known 9P failure, not scientific validation.

Run intended RED first; after T1-T5 the full test must go GREEN without new architecture:

```bash
uv run pytest -q tests/unit/test_9p2_track_a_regression.py
uv run pytest -q \
  tests/unit/test_9p2_track_a_regression.py \
  tests/unit/test_longitudinal_derivations.py \
  tests/unit/test_semantic_view.py \
  tests/unit/test_admission.py
```

If an approved-contract production bug is exposed, fix it in a separate RED/GREEN commit before the regression commit. If the missing behavior is architecturally material, stop.

- [ ] Commit:

```bash
git add tests/unit/test_9p2_track_a_regression.py
git commit -m "test: prove Track A contrastive correction lifecycle"
```

---

## 9. Task T7 — Full verification and architecture gate

No live calls and no experiment artifacts.

### Focused verification

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

Expected: zero failures, zero network.

### Full repository verification

Run fresh:

```bash
uv run pytest -v
uv run ruff check .
uv run mypy src
git diff --check
git status --short
```

Expected: 0 pytest failures, 0 ruff errors, 0 mypy errors, no whitespace errors, clean status.

### Explicit architecture checks

Prove from source/tests/diff:

- [ ] `CALLS_PER_DELTA == 2`;
- [ ] address threshold 200;
- [ ] diff context lines 3;
- [ ] per-transition limit 65,536;
- [ ] total comparison-context limit 131,072;
- [ ] historical base xAI policy/version/system hash unchanged;
- [ ] contrastive policy is `intent-v2-9p2-v1` with a pasted hash matching fresh bytes;
- [ ] output schema hash remains `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`;
- [ ] no new `JudgmentKind` or event type;
- [ ] no comparison-context field in durable `SemanticState`;
- [ ] old 9P experiment directory byte-unchanged from implementation starting SHA;
- [ ] no lexical/embedding/fuzzy/semantic-scoring/LLM-diff/full-history fallback path;
- [ ] Track C/T3 observation coverage was not silently claimed or implemented.

Use the actual implementation starting SHA in `git diff <start>...HEAD`; do not substitute memory.

### Review gate

Invoke `superpowers:requesting-code-review` on the complete implementation diff. Review specifically for:

1. deterministic semantic conclusions leaking into compiler selection;
2. historical comparison evidence becoming citable;
3. any unbounded/truncating context path;
4. third reasoner call or retry;
5. mutation/redefinition of old 9P xAI policy or experiment artifacts;
6. output-schema drift;
7. divergence between request-assembly tests and actual orchestrator behavior.

Fix every Critical/Important finding with RED/GREEN and re-run all verification.

### Completion report

Report exact:

- implementation starting SHA;
- all task commit SHAs/messages;
- changed files;
- tests added/modified;
- focused/full pytest counts;
- ruff/mypy/diff-check results;
- historical 9P prompt/policy/schema identities;
- new contrastive prompt/policy identity;
- proof no live calls;
- proof old 9P artifacts untouched;
- code-review result;
- clean `git status --short`.

Do **not** claim the 9P2 scientific hypothesis passed. The maximum conclusion after T7 is: implementation contract and known Track A regression locally verified.

---

## 10. Separate scientific-validation gate

After T7 is accepted by the architect, stop.

The next work item is a **separate preregistered unseen 9P2 lifecycle experiment**. Its fixture, tracked loci, expectations, adjudication rules, context/token metrics, call/cost ceilings, exact contrastive policy hash, and fail-fast/no-retry discipline must be sealed before the first live provider call.

Track A may be a regression/control only; it cannot count as new evidence because 9P2 was designed from that failure.

The unseen experiment must test at minimum:

1. correctness on a lifecycle not used to design 9P2;
2. no duplicate semantic identity for a changed locus;
3. correct support versus correction behavior under governed supersession;
4. persistent context materially smaller than reconstruction;
5. every rehydrated historical byte has a structural inclusion reason;
6. replay/governance integrity;
7. no deterministic semantic authority in the compiler.

9Q cross-model inheritance remains unauthorized until that experiment passes or the architect explicitly revises the gate.
