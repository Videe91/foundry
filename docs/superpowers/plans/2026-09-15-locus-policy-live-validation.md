# Locus Policy Live Validation — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-09-15-locus-policy-live-validation-design.md` (binding; amended at `4dfef87`).
**Experiment:** `intent-v2-locus-validation-v1`. **Policy under test:** `intent-v2-locus-v1` (`XAILocusSemanticReasoner`; prompt sha `e0547cfeb8d4ad8266c6610793fbd172b3a93cd00661c806b465cb7ad73deaa1`; schema sha `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`).
**Baseline:** every task starts from a descendant of `b34b987454c942965fa09a556725693896ecc426` on `feat/intent-intelligence-v2` in the existing worktree `/Users/vineetpandey/Desktop/foundry/.claude/worktrees/intent-intelligence-v2` (never create another worktree).
**Workflow:** strict TDD (RED for the intended reason → minimum GREEN → checks → one commit per task), Superpowers subagent-driven development with a fresh implementer and an independent reviewer per task, ledger rulings.

## Global constraints (binding for every task)

1. ZERO provider/model/judge calls anywhere in implementation or tests. Never construct `XAILocusSemanticReasoner`/`XAISemanticReasoner`/`XAIContrastiveSemanticReasoner` in a test; never read `XAI_API_KEY` (tests use a `PoisonedEnv`); block sockets (`socket.socket.connect`, `socket.create_connection`) in every test module that touches the reasoner port. Never run `--live`. Never push.
2. Do NOT modify: `src/foundry/domain|application|ports|adapters` (the locus policy at `e0f5e42` is production and frozen for this experiment), `src/foundry/experiments/contrastive_unseen`, `src/foundry/experiments/longitudinal`, `src/foundry/experiments/long_horizon_bounded`, any directory under `docs/superpowers/experiments/`, the spec, this plan, `evals/`. If a task needs a change there, STOP and report — it is an architectural finding (Law of Descent), not permission.
3. New code lives only under `src/foundry/experiments/locus_validation/`, the three scripts named in T8, and the tests named per task. Reuse by import only: `RequestRecord` (`contrastive_unseen.records`), `canonical_bytes/canonical_sha256/pretty_json` (`contrastive_unseen.artifacts`), `CommandRunnerLike/GateResult/all_passed` (`contrastive_unseen.integrity`), `GitCliLike`, `RequestReferenceSnapshot`, `snapshot_request_references`, `CallJudgments`, `request_only_reference_check`, `ReferenceSnapshotMismatch`, `PreflightGateMissing` (`long_horizon_bounded.runner` / `.integrity`), `LeakageNeedle`, `NeedleKind`, `matches` (`long_horizon_bounded.leakage`), `redact_secrets`, `contains_secret_shape` (`longitudinal.artifacts`), `replay_matches` (`longitudinal.scoring`), `assimilate_delta`, `SemanticGovernor`, `InMemoryEventStore`, `render_request`, the locus policy constants. The 9P2 `RecordingReasoner` and 9P3 `BudgetedReasoner` are NOT reused (they pin historical policies).
4. Request-path modules (`corpus.py`, `protocol.py`, `recording.py`, `runner.py`) never import `expectations.py`, `evaluation.py`, `leakage.py`, `integrity.py` or `artifacts.py`, and never contain answer-key wording, class names, case ids, outcome names or failure tags. Deterministic code never decides meaning: no lexical/similarity/ontology logic; case evaluation reads only ids, kinds, routes, counts and structural values.
5. The corpus (spec §5), expected states (§6), assertion sets and tags (§7.1), semantic questions (§7.2), ceilings (§12: 8 / 0 / 0 / 0 / 0 / 2.00), artifact paths (§13: 21 raw paths), gate list (§8: 18 gates), scoring (§14) and outcome vocabulary are scientific design — transcribe them verbatim; never adjust them to make code or tests easier.
6. Preflight is non-consuming and read-only (spec §10); consumption is one atomic write immediately before the first provider-call attempt; raw freeze precedes adjudication and adjudication may change only `verdicts.json` and `report.md` (§11). No task may weaken these.
7. Record-shape ruling: the experiment reuses `RequestRecord` and `RequestReferenceSnapshot` unchanged with `arm="F"` fixed (the locus policy is the successor of the contrastive F path; these types carry no policy pinning) so the 9P3 `request_only_reference_check` is reused rather than re-implemented; the ledger identity (`"alpha"`/`"beta"`) lives on the experiment's own `LedgerRecord`/artifact documents, never inferred from `arm`.
8. Tooling: `uv run pytest -q <files> -p no:cacheprovider`, `uv run ruff check <paths>`, `uv run ruff format --check <paths>`, `uv run mypy src`; always with `env -u XAI_API_KEY`. Python 3.12, Pydantic v2 `FrozenModel` (`foundry.domain.common`). Plain single git commands (the sandbox refuses compound git); commits via `git commit -F <file>` with trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; never amend/rebase/force/push.

## File map

| file | responsibility | task |
|---|---|---|
| `src/foundry/experiments/locus_validation/__init__.py` | package docstring: the law (AI decides meaning; the harness governs structure; nothing here selects an outcome) | T1 |
| `corpus.py` | the 16 frozen evidence items of spec §5 as `EvidenceItem` builders per ledger and T; `evidence_records()`; `corpus_sha256()`; `LEDGERS` | T1 |
| `expectations.py` | HIDDEN answer key: case table, expected states, deterministic assertion definitions and tags, semantic questions, scoring rule, outcome vocabulary; `expectations_document()`; never imported by a request-path module | T1 |
| `protocol.py` | experiment version, ledger/scope/project ids, ceilings, frozen identity literals, `Ledger` literal, `CALLS_PER_DELTA` re-export | T2 |
| `recording.py` | `LocusRecordingReasoner`: identity guard (construction + per call), budget/ceiling enforcement, `RequestRecord` + `RequestReferenceSnapshot` capture, receipts and draft payloads | T2 |
| `runner.py` | `run_ledger` (seed delta then revision delta over a fresh governor), `run_experiment` (α then β, fail-fast, `NOT_RUN` fill), `LedgerRecord`, `RunResult`, `RunStatus` | T3 |
| `evaluation.py` | deterministic case assertion sets of spec §7.1 over a `LedgerRecord` → `CaseResult` with failure tags; per-ledger and per-run | T4 |
| `integrity.py` | the 18 preflight gates (§8) and post-run verdicts L1–L9 with `failed_ledgers` | T5 |
| `leakage.py` | typed needle set (§9) from `expectations`, eight real skeletons, `needle_set_sha256`, `run_leakage_gate`, `request_path_import_gate` | T6 |
| `artifacts.py` | `ExperimentManifest`, `build_manifest`, `write_preregistration`, `write_consumption`, `write_run_artifacts`, `verdicts_document`, `render_report`, `Adjudication`, `write_adjudication`, `RAW_ARTIFACT_PATHS` | T7 |
| `scripts/prepare_locus_validation.py` | seal tooling (`main(argv, *, cwd, git=None)`) | T8 |
| `scripts/run_locus_validation.py` | `--preflight-only` (non-consuming) / `--live` (consuming transition, abort preservation) | T8 |
| `scripts/adjudicate_locus_validation.py` | offline adjudication entry point | T8 |

Tests: `tests/unit/test_locus_validation_corpus.py`, `_expectations.py` (T1); `_protocol.py`, `_recording.py` (T2); `_runner.py` (T3); `_evaluation.py` (T4); `_integrity.py` (T5); `_leakage.py` (T6); `_artifacts.py` (T7); `tests/integration/test_locus_validation_entrypoint.py` (T8).

Generic identities reused verbatim from the frozen 9P3 experiment package, by import: `HISTORICAL_PRESERVATION_BASE_SHA`-style base is NEW for this experiment (`DESIGN_BASE_SHA`, see T2); the seven historical dirs = 9P3's six `HISTORICAL_ARTIFACT_DIRS` + `"docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/"`.

---

## T0 — Isolated workspace and baseline qualification (no commit)

- [ ] Confirm `git rev-parse HEAD` descends from `b34b987…`, `git status --short` empty, `XAI_API_KEY` unset (presence-only).
- [ ] Run the baseline once: `env -u XAI_API_KEY uv run pytest -q -p no:cacheprovider tests/unit/test_locus_policy.py tests/unit/test_compatible_extension_lifecycle.py tests/unit/test_admission.py` (must pass) and `uv run mypy src` (clean).
- [ ] Create the SDD workspace (`.superpowers/sdd/<plan-basename>/`), the ledger, implementer/reviewer contracts (copy the 9P3 contracts; replace the frozen-path list with Global Constraint 2 above).

---

## T1 — Corpus and frozen semantic expectations

**Commit:** `experiment: add locus validation corpus and expectations`

**Files:** create `src/foundry/experiments/locus_validation/__init__.py`, `corpus.py`, `expectations.py`; tests `tests/unit/test_locus_validation_corpus.py`, `tests/unit/test_locus_validation_expectations.py`.

**Interfaces — produces:**

```python
# corpus.py  (request path; imports foundry.domain.evidence only)
Ledger = Literal["alpha", "beta"]
LEDGERS: Final[tuple[Ledger, ...]] = ("alpha", "beta")
PROJECT_IDS: Final[dict[Ledger, str]] = {"alpha": "PROJ-LV-ALPHA", "beta": "PROJ-LV-BETA"}
SCOPES: Final[dict[Ledger, str]] = {"alpha": "keyring", "beta": "relay"}
DOCUMENTS: Final[dict[Ledger, tuple[str, ...]]]            # ("A1","A2","A3","A4") / ("B1","B2","B3","B4")
ARTIFACT_REFS: Final[dict[str, str]]                        # "A1" -> "keyring/spec/credential-revocation.md", ... exactly spec §5
def evidence_id(document: str, t: Literal[1, 2]) -> str     # f"EV-LV-{document}-T{t}"
def section_text(document: str, t: Literal[1, 2]) -> str    # the byte-exact fenced block of spec §5 (trailing newline preserved)
def delta(ledger: Ledger, t: Literal[1, 2]) -> tuple[EvidenceItem, ...]   # the four items of that T in document order; T2 items supersede T1 (same artifact_ref); scope=(SCOPES[ledger],); source_ref "experiment://locus-validation/<ledger>/T<t>/<doc>"; observed_at a fixed frozen datetime
class EvidenceRecord(FrozenModel): evidence_id; ledger; document; t; artifact_ref; supersedes_evidence_id: str | None; content_sha256; chars
def evidence_records() -> tuple[EvidenceRecord, ...]       # 16, alpha then beta, T1 then T2, document order
def corpus_sha256() -> str                                  # canonical_sha256 of [record dumps + content] — the ONLY corpus hash implementation
```

```python
# expectations.py  (hidden answer key; never in the request path)
CASE_IDS: Final = ("S01", "V01", "V02", "V03", "V04", "V05")
SemanticClass = Literal["SEED", "COMPATIBLE_EXTENSION", "DISTINCT_LOCUS", "RESTATEMENT", "CORRECTION"]
class Case(FrozenModel): id: str; semantic_class: SemanticClass; document: str  # per ledger: the revised document carrying it ("A1"/"B1" for V01, "A2"/"B2" for V02 and V03, ...)
CASES: Final[dict[Ledger, tuple[Case, ...]]]
FAILURE_TAGS: Final = ("OVER_SPLIT","UNDER_SPLIT","MISSING_EXTENSION","DUPLICATE_ASSERTION","MISSING_SUPERSEDE","WRONG_SUPERSEDE_TARGET","CONFLICT_INSTEAD_OF_CORRECTION","UNGOVERNED_SUPERSEDE","WRONG_BIND","EXTRA_DRAFT")
EXPECTED_STATE: Final[dict[str, str]]                       # the §6 sentences, keyed "T1", "T2"; PROSE needles
ASSERTION_TEXT: Final[dict[str, str]]                       # §7.1 rows rendered as prose per case id; PROSE needles
SEMANTIC_QUESTIONS: Final[dict[str, str]]                   # {"A-S01": ..., "A-V01": ..., "A-V02": ..., "A-V03": ..., "A-V05": ...} verbatim from §7.2 (per ledger the question names the ledger's propositions)
SEMANTIC_ASSERTION_IDS: Final = ("A-S01", "A-V01", "A-V02", "A-V03", "A-V05")   # V04 has none by design
OUTCOMES: Final = ("LOCUS_POLICY_VALIDATED", "LOCUS_POLICY_NOT_VALIDATED", "EXPERIMENT_INCONCLUSIVE")
HYPOTHESES: Final[dict[str, str]]                           # H0..H4 sentences of §2
class CaseOutcomeRule(FrozenModel): ...                     # §14 as data: a case passes iff structural AND (semantic answer is True or no semantic assertion)
def experiment_outcome(*, rule_zero: bool, case_passes: Mapping[tuple[Ledger, str], bool]) -> str   # §14: rule 0 -> INCONCLUSIVE; all 12 True -> VALIDATED; else NOT_VALIDATED. Pure; called ONLY by artifacts.write_adjudication
def expectations_document() -> dict[str, Any]              # everything above, canonical, deterministic
```

- [ ] **Step 1: Tests (RED)** — corpus: 16 items, ids `EV-LV-{A|B}{1..4}-T{1,2}`, each T2 supersedes its T1 with the same `artifact_ref`, scopes/projects per ledger, `section_text` for every (document, t) equals the fenced block of spec §5 byte-for-byte (the test embeds the spec blocks as literals — the spec is the source of truth), no document contains any of: `RESTATEMENT`, `EXTENSION`, `CORRECTION`, `DISTINCT`, `S01`, `V0`, `VALIDATED`, `INCONCLUSIVE`, `Orion`, `cancel`, `EV-O-`; `corpus_sha256()` deterministic and equal to a test-side recomputation; `evidence_records()` order. Expectations: `CASE_IDS`, tags, outcomes verbatim; `experiment_outcome` truth table (rule 0 wins; any False → NOT_VALIDATED; all 12 True → VALIDATED; exactly 12 keys required, else `ValueError`); `SEMANTIC_ASSERTION_IDS` excludes V04; `expectations_document()` deterministic; the module is not imported by `corpus.py` (AST).
- [ ] **Step 2: Run RED** → `ImportError` for both modules.
- [ ] **Step 3: Implement** minimally; the section texts are module-level string constants transcribed from the spec.
- [ ] **Step 4: GREEN + ruff + format + mypy + commit.**

---

## T2 — Protocol, identity constants and the recording/budgeted locus reasoner

**Commit:** `experiment: add locus validation protocol and recording reasoner`

**Files:** create `protocol.py`, `recording.py`; tests `tests/unit/test_locus_validation_protocol.py`, `tests/unit/test_locus_validation_recording.py`.

**Interfaces — produces:**

```python
# protocol.py (request path)
EXPERIMENT_VERSION: Final = "intent-v2-locus-validation-v1"
ARTIFACT_FORMAT_VERSION: Final = 1
BASELINE_SHA: Final = "b34b987454c942965fa09a556725693896ecc426"
DESIGN_BASE_SHA: Final = "…"   # the 40-hex sha of the commit that added THIS plan (the plan commit is the historical-preservation baseline: every historical dir exists there); the T2 implementer pastes it from `git log --diff-filter=A -- docs/superpowers/plans/2026-09-15-locus-policy-live-validation.md` and a test pins the literal's shape
HISTORICAL_ARTIFACT_DIRS: Final[tuple[str, ...]] = (
    "docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/",
    "docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood/",
    "docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/",
    "docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/",
    "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/",
)   # seven; the first six are the 9P3 list verbatim
PREDECESSOR_RAW_RUN_SHA: Final = "f045612e9ec9917b73649175cf08f91f087f2828"
PREDECESSOR_ADJUDICATION_SHA: Final = "3c30c16193dae6a9a03fe630f2ca33bf2a2e8c13"
PREDECESSOR_ARTIFACT_DIR: Final = "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/"
PROVIDER, MODEL, REASONING_EFFORT = "xai", "grok-4.6", "high"
GRPC_DNS_RESOLVER_ENV, GRPC_DNS_RESOLVER_FROZEN = "GRPC_DNS_RESOLVER", "native"
POLICY_VERSION_FROZEN: Final = "intent-v2-locus-v1"
PROMPT_SHA256_FROZEN: Final = "e0547cfeb8d4ad8266c6610793fbd172b3a93cd00661c806b465cb7ad73deaa1"
OUTPUT_SCHEMA_SHA256_FROZEN: Final = "ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851"
HISTORICAL_PROMPT_SHA256S: Final = {
    "intent-v2-9p-v4": "24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1",
    "intent-v2-9p2-v1": "a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410",
}
MAX_FRONTIER_CALLS, MAX_JUDGE_CALLS, MAX_SEMANTIC_RETRIES, MAX_SAME_CELL_RERUNS, MAX_HUMAN_AUTHORIZATIONS = 8, 0, 0, 0, 0
MAX_COST_USD: Final = 2.0
CEILING_KEYS: Final = ("max_frontier_calls","max_judge_calls","max_semantic_retries","max_same_cell_reruns","max_human_authorizations","max_provider_cost_usd")
CALLS_PER_LEDGER: Final = 4          # 2 deltas × CALLS_PER_DELTA
DELTAS: Final = (1, 2)               # T1 seed, T2 revision
EXPERIMENT_ARTIFACT_DIR: Final = "docs/superpowers/experiments/2026-09-15-locus-validation-v1/"
PREREGISTRATION_FILE_NAMES: Final = ("manifest.json", "expectations.json")
```

```python
# recording.py (request path; imports adapter constants + contrastive_unseen.records.RequestRecord + long_horizon_bounded.runner.RequestReferenceSnapshot/snapshot_request_references by import)
class IdentityDrift(RuntimeError)
def observed_identity(inner: SemanticReasoner) -> dict[str, str | bool]   # fingerprint provider/model/policy; class policy_version; sha256(class system_instruction); include_comparison_context; reasoning_effort (attr or _reasoning_effort) — instance-resolved reads
def require_locus_identity(inner: SemanticReasoner) -> None              # every observed value must equal the frozen protocol literals; else IdentityDrift
class ExperimentBudget: frontier_calls: int; provider_cost_usd: Decimal; judge_calls: int = 0; human_authorizations: int = 0; def snapshot() -> BudgetSnapshot
class BudgetExceeded(RuntimeError)
class LocusRecordingReasoner:                                          # SemanticReasoner
    def __init__(self, inner, *, ledger: Ledger, budget: ExperimentBudget)   # require_locus_identity at construction
    fingerprint -> inner.fingerprint
    def begin_delta(self, t: int) -> None                                # resets the per-delta call counter (max 2)
    def propose(self, request) -> tuple[SemanticJudgment, ...]:
        # order: identity re-check (IdentityDrift before forwarding) → ceiling check (frontier_calls + 1 > MAX_FRONTIER_CALLS → BudgetExceeded BEFORE forwarding; third call in a delta → BudgetExceeded) → cost check (recorded cost > MAX_COST_USD → BudgetExceeded) → capture reference snapshot from the exact request → increment frontier_calls → forward → record RequestRecord(arm="F", t, call_number, policy_version, system_prompt_sha256, rendered_user_request via render_request(include_comparison_context=True), request_sha256, ids, allowed kinds, comparison chars) → collect receipts/draft payloads (inner.receipts / inner.draft_payloads when exposed) → accumulate cost
    records: tuple[RequestRecord, ...]; snapshots: tuple[RequestReferenceSnapshot, ...]; receipts: tuple[Any, ...]; draft_payloads: tuple[Any, ...]
```

- [ ] **Step 1: Tests (RED)** — protocol literals verbatim (ceilings, ids, hashes equal the in-process adapter constants: `PROMPT_SHA256_FROZEN == LOCUS_SYSTEM_INSTRUCTION_SHA256 == sha256(LOCUS_SYSTEM_INSTRUCTION)`, `POLICY_VERSION_FROZEN == LOCUS_POLICY_VERSION`, schema sha == `semantic_output_schema_sha256()`, historical prompt shas unchanged; `DESIGN_BASE_SHA` is an ancestor of HEAD via a fake-free `git merge-base --is-ancestor` in a subprocess is NOT allowed in unit tests — instead assert the literal is 40-hex and that every `HISTORICAL_ARTIFACT_DIRS` entry exists in the working tree). Recording: fakes mirroring the real class attributes (`policy_version`, `system_instruction`, `include_comparison_context`, `reasoning_effort`, `fingerprint`) — a 9p2-v1 fake, a 9p-v4 fake, a locus fake with a tampered instance `system_instruction`, wrong model, wrong effort → `IdentityDrift` at construction; per-call drift (mutate after construction) → `IdentityDrift` before forwarding (the fake's call count stays 0); **8-call ceiling: the 9th `propose` raises `BudgetExceeded` before forwarding** (fake never sees call 9); third call in one delta refused before forwarding; cost over 2.00 refuses the next call before forwarding; `judge_calls` and `human_authorizations` are constants 0 with no mutator; every forwarded call yields exactly one `RequestRecord` bound 1:1 to a `RequestReferenceSnapshot` (`arm == "F"`, matching `t`, `call_number`, `request_sha256`, identical id tuples); the record's `rendered_user_request` equals `render_request(request, include_comparison_context=True)`; the provider raising leaves the record absent and the snapshot absent (no fabricated record) and `frontier_calls` incremented (admitted, not answered — documented).
- [ ] **Step 2: RED** → `ImportError`. **Step 3: Implement. Step 4: GREEN + checks + commit.**

---

## T3 — Single-ledger runner and the two-ledger experiment walk

**Commit:** `experiment: add locus validation runner`

**Files:** create `runner.py`; test `tests/unit/test_locus_validation_runner.py`.

**Interfaces — produces:**

```python
class RunStatus(StrEnum): NOT_RUN, ABORTED_PROVIDER, ABORTED_MODEL_CONTRACT, ABORTED_RUNTIME, ABORTED_BUDGET, ABORTED_IDENTITY, COMPLETED
LedgerStatus = Literal["COMPLETED", "FAILED", "NOT_RUN"]
class DeltaRecord(FrozenModel): t; requests: tuple[RequestRecord, ...]; reference_snapshots: tuple[RequestReferenceSnapshot, ...]; stage_decisions: tuple[tuple[AdmissionDecision, ...], tuple[AdmissionDecision, ...]]; draft_payloads; receipts; pending_supersede_judgment_ids; state_snapshot: IntentState | None; view_snapshot: CurrentSemanticView | None
class LedgerRecord(FrozenModel): ledger: Ledger; project_id; scope; status: LedgerStatus; error: str | None; deltas: tuple[DeltaRecord, ...] (0..2); ledger_events: tuple[StoredEvent, ...]; final_state: IntentState | None; final_view: CurrentSemanticView | None; replay: ReplayResult | None
class RunResult(FrozenModel): status: RunStatus; error: str | None; ledgers: tuple[LedgerRecord, LedgerRecord]  # alpha, beta always both present; budget: BudgetSnapshot
def run_ledger(*, ledger: Ledger, reasoner: LocusRecordingReasoner, clock, id_factory) -> LedgerRecord   # fresh InMemoryEventStore + SemanticGovernor(project_id, AdmissionPolicy()); for t in DELTAS: reasoner.begin_delta(t); assimilate_delta(governor, reasoner, delta(ledger, t), scope) inside the abort-recording try; capture DeltaRecord after each delta (state + derive_view); on exception: status FAILED, error redacted "type: message", partial deltas kept, remaining deltas absent; replay_matches over the final ledger when COMPLETED
def run_experiment(*, inner: SemanticReasoner, budget: ExperimentBudget, clock, id_factory, progress: list[LedgerRecord] | None = None) -> RunResult   # ONE LocusRecordingReasoner per ledger sharing `budget`; alpha then beta; first failure → later ledger NOT_RUN; classify status from the exception type (XAIProviderError → ABORTED_PROVIDER; SemanticOutputError / ReferenceSnapshotMismatch → ABORTED_MODEL_CONTRACT; BudgetExceeded → ABORTED_BUDGET; IdentityDrift → ABORTED_IDENTITY; else ABORTED_RUNTIME); never retries; never calls select/outcome functions; never imports expectations/evaluation/leakage/integrity/artifacts
```

- [ ] **Step 1: Tests (RED)** — scripted reasoners (one batch per call; callable batches that inspect the real `ReasoningRequest`) with locus-identity fakes; sockets blocked. Prove: a scripted success makes exactly 8 forwarded calls in order α-T1c1, α-T1c2, α-T2c1, α-T2c2, β-…; both ledgers COMPLETED with 2 deltas each; each delta has 2 requests + 2 snapshots bound 1:1; T1 Call 1 shows 0 known addresses and T2 Call 1 shows exactly the 4 T1 addresses with their live claims; T2 evidence items are the T2 delta only and the comparison context carries the four transitions; fresh store per ledger (β's Call 1 sees no α address); replay equality on success; a provider failure at call 3 → α FAILED with delta T1 preserved, β NOT_RUN, status ABORTED_PROVIDER, no further forwarded calls; `SemanticOutputError` at call 6 → α COMPLETED preserved, β FAILED, ABORTED_MODEL_CONTRACT; a 9th call is impossible (ceiling); `KeyboardInterrupt` propagates after recording; `runner.py` imports none of `expectations`, `evaluation`, `leakage`, `integrity`, `artifacts` (AST) and never references the outcome names.
- [ ] **Step 2: RED** → `ImportError`. **Step 3: Implement. Step 4: GREEN + checks + commit.**

---

## T4 — Deterministic case evaluation

**Commit:** `experiment: add locus validation case evaluation`

**Files:** create `evaluation.py`; test `tests/unit/test_locus_validation_evaluation.py`.

**Interfaces — produces:**

```python
class CaseResult(FrozenModel): ledger: Ledger; case_id: str; structural_passed: bool | None   # None when the ledger did not run that delta; tags: tuple[str, ...]; detail: str; evidence: dict[str, Any]   # ids only: bound address, new claim ids, supersede judgment id, counts
def evaluate_ledger(record: LedgerRecord) -> tuple[CaseResult, ...]     # S01, V01..V05 in order, spec §7.1 verbatim
def evaluate_run(run: RunResult) -> tuple[CaseResult, ...]              # 12 results, alpha then beta
```

Evaluation reads: `stage_decisions` (routes), the judgments in `ledger_events` (kinds, cited evidence ids, address ids, target judgment ids, admission routes), `final_state.semantic` (addresses in scope created by active judgments; live claims; applied ids; pending supersedes via `final_view.pending_judgment_ids`). The T1 address of document `Di` is the address created by the applied `CREATE_ADDRESS` whose candidate cites `EV-LV-<Di>-T1` (structural, by evidence id). Tags exactly per spec §7.1; a case with a missing delta is `structural_passed=None` with tag `()` and detail "delta not run".

- [ ] **Step 1: Tests (RED)** — build `LedgerRecord`s through the REAL governor + `assimilate_delta` with specification reasoners (as in `tests/unit/test_compatible_extension_lifecycle.py`) for: the fully correct α and β stories (all six cases pass, tags empty); then one mutation per tag: OVER_SPLIT (a CREATE citing `D1'`), UNDER_SPLIT (V03 asserted at `X2`, no CREATE), MISSING_EXTENSION (no new claim at `X1`), DUPLICATE_ASSERTION (an ASSERT citing `D3'`), MISSING_SUPERSEDE, WRONG_SUPERSEDE_TARGET (supersede of a claim at `X1`), CONFLICT_INSTEAD_OF_CORRECTION, WRONG_BIND (`D3'` bound to `X4`), EXTRA_DRAFT; UNGOVERNED_SUPERSEDE via a hand-built record whose ledger shows an applied model supersede; a ledger FAILED after T1 → S01 evaluated, V01–V05 `None`; NOT_RUN ledger → all `None`; `evaluate_run` returns 12 results in order; the module never imports the adapter and contains no wording comparison (AST: no `.lower()`, `in <str>` over text, `difflib`, `re` on claim text).
- [ ] **Step 2: RED** → `ImportError`. **Step 3: Implement. Step 4: GREEN + checks + commit.**

---

## T5 — Integrity: 18 preflight gates and verdicts L1–L9

**Commit:** `experiment: add locus validation integrity gates`

**Files:** create `integrity.py`; test `tests/unit/test_locus_validation_integrity.py`.

**Interfaces — produces:**

```python
GATE_NAMES: Final = ("head_equals_final_seal","worktree_clean","seal_descends_from_baseline","locus_policy_frozen","locus_prompt_hash_frozen","output_schema_hash_frozen","historical_prompts_unchanged","model_configuration_frozen","calls_per_delta_is_2","evidence_manifest_frozen","ceilings_frozen","expectations_frozen","answer_key_not_imported_by_request_path","leakage_gate_passes","grpc_dns_resolver_is_native","historical_artifacts_unchanged","predecessor_commits_unchanged","no_raw_artifacts_exist")   # exactly 18, spec §8 order; NO test-suite gate
MANIFEST_KEY_* (harness_code_sha, policy_version, prompt_sha256, output_schema_sha256, provider, model, reasoning_effort, grpc_dns_resolver, evidence, corpus_sha256, ceilings, expectations_sha256, leakage_needle_set_sha256, historical_artifact_tree_hashes, historical_preservation_base_sha, predecessor_raw_run_sha, predecessor_adjudication_sha, raw_artifact_paths)
def preflight(*, git: GitCliLike, frozen_sha: str, manifest: Mapping[str, Any], expectations_bytes: bytes, request_path_sources: Mapping[str, str], leakage: LeakageResult, observed_grpc_dns_resolver: str | None, out_dir: Path) -> tuple[GateResult, ...]   # pure: no subprocess except through `git`, no network, no key, no write; `no_raw_artifacts_exist` inspects out_dir for RAW_ARTIFACT_PATHS (imported from artifacts — allowed: integrity is not a request-path module)
VERDICT_IDS: Final = ("L1",...,"L9")
class IntegrityVerdict(FrozenModel): id; passed: bool | None; detail; applies_to: tuple[Ledger, ...]; failed_ledgers: tuple[Ledger, ...]   # same validators as 9P3 spec §12.1 (subset, canonical order alpha, beta, empty on pass, None ⇒ empty)
def integrity_verdicts(run: RunResult, *, preflight_gates: tuple[GateResult, ...], case_results: tuple[CaseResult, ...]) -> tuple[IntegrityVerdict, ...]   # L1 two calls per completed delta; L2 no third/judge/retry (frontier_calls == records, judge_calls == 0); L3 request_only_reference_check per ledger (pairs record+snapshot+model judgments from that delta's events); L4 replay per completed ledger; L5 receipts/requests/events reconcile; L6 no applied model SUPERSEDE, human_authorizations == 0; L7 no IdentityDrift recorded; L8 cost ≤ 2.00 and frontier_calls ≤ 8; L9 every CaseResult with structural_passed False → L9 fails naming (ledger, case, tags). Per-ledger attribution; a whole-gate exception → passed False, failed_ledgers ()
```

- [ ] **Step 1: Tests (RED)** — FakeGit (`head`, `dirty`, `parents`, `is_ancestor`, `changed_paths`, `show_bytes`, `tree_sha`) with a realistic table: seal sha with single parent == harness sha, parent..seal changes exactly the two prereg paths, `BASELINE_SHA`/`DESIGN_BASE_SHA`/predecessor shas ancestors, tree_sha equal at base and seal for all seven dirs, no change under the 9P3 dir since `3c30c16`; a manifest fixture from T7's `build_manifest`-shaped dict (until T7 lands, a literal dict with the exact keys); every gate PASSES on correct input and FAILS on one corruption each (dirty tree; wrong prompt hash; historical prompt changed via monkeypatched constant; model config drift; tampered expectations bytes; missing request-path source; leakage failed; resolver None/""/"ares"/"Native"; one historical tree differing; 9P3 dir changed / predecessor not ancestor; a stray `consumption.json` or `L-beta/ledger.json` present); the gate list contains no test-suite gate and `preflight` never calls `subprocess` (AST); post-run: a scripted COMPLETED run passes L1–L9; mutations: one-call delta (L1), a third record (L2), a snapshot re-ordered (L3 mismatch → FAIL), replay mismatch (L4), receipt count mismatch (L5), hand-built applied model supersede (L6), recorded drift (L7), cost 2.01 / 9 calls (L8), a failing CaseResult (L9 names ledger+case+tags); `failed_ledgers` attribution per ledger; verdict validators.
- [ ] **Step 2: RED. Step 3: Implement. Step 4: GREEN + checks + commit.**

---

## T6 — Typed leakage gate

**Commit:** `experiment: add locus validation leakage gate`

**Files:** create `leakage.py`; test `tests/unit/test_locus_validation_leakage.py`.

**Interfaces — produces:**

```python
SKELETON_IDS: Final = ("ALPHA_SEED_CALL1","ALPHA_SEED_CALL2","ALPHA_REVISION_CALL1","ALPHA_REVISION_CALL2","BETA_SEED_CALL1","BETA_SEED_CALL2","BETA_REVISION_CALL1","BETA_REVISION_CALL2")
def typed_needles() -> tuple[LeakageNeedle, ...]     # PROSE: HYPOTHESES, EXPECTED_STATE, ASSERTION_TEXT, SEMANTIC_QUESTIONS values; CANONICAL_LABEL: OUTCOMES, FAILURE_TAGS, "RESTATEMENT","COMPATIBLE_EXTENSION","CORRECTION","DISTINCT_LOCUS", VERDICT_IDS L1..L9, SEMANTIC_ASSERTION_IDS; CHECKPOINT_LABEL: CASE_IDS; sorted by (kind, value); reuses long_horizon_bounded.leakage.LeakageNeedle/matches
def needles() -> tuple[str, ...]; def needle_set_sha256() -> str   # 9P3 §15.1 recipe (kind\x00value, sorted, \x1e, sha256)
def build_skeletons() -> dict[str, str]              # real SemanticGovernor over opaque stand-in evidence ("<EVIDENCE:EV-LV-A1-T1>" content, real ids/refs/lineage, real scopes) → real assemble_assimilation_request / assemble_claim_request → render_request(include_comparison_context=True); haystack = LOCUS_SYSTEM_INSTRUCTION + "\n" + rendered; seed skeletons from an empty state; revision skeletons from a state seeded with four opaque addresses/claims minted through the governor with scripted structural judgments (no wording)
class LeakageResult(FrozenModel): passed; needle_set_sha256; skeletons: tuple[SkeletonRecord, ...]; prompt_sha256; matched_needle; matched_needle_kind; matched_skeleton_id
def run_leakage_gate(*, extra_harness_text: tuple[str, ...] = ()) -> LeakageResult   # evidence-content substitution only; fail closed on first match
REQUEST_PATH_MODULES: Final = ("corpus.py", "protocol.py", "recording.py", "runner.py")
def request_path_import_gate(sources: Mapping[str, str]) -> tuple[bool, str]   # rejects any import of .expectations/.evaluation/.leakage/.integrity/.artifacts of this package in any form; all four keys required
```

- [ ] **Step 1: Tests (RED)** — inventory by kind; hash recipe recomputed; default gate PASSES over all eight skeletons (the production prompt's lower-case lifecycle words are not matches; the upper-case tokens are); injected `("COMPATIBLE_EXTENSION",)` FAILS with kind CANONICAL_LABEL while `("compatible extension",)` PASSES; `("V03",)` FAILS, `("EV-LV-A3-T1",)` PASSES (identifier-bounded); an expected-state sentence with changed casing/whitespace FAILS with kind PROSE while the same sentence inside stand-in evidence content PASSES; skeleton set exactly `SKELETON_IDS`; no Orion/9P3 text in skeletons; the four real request-path sources PASS the import gate and each forbidden import form FAILS; a missing source FAILS.
- [ ] **Step 2: RED. Step 3: Implement. Step 4: GREEN + checks + commit.**

---

## T7 — Artifacts: manifest, preregistration, consumption, raw writer, adjudication

**Commit:** `experiment: add locus validation artifacts and adjudication`

**Files:** create `artifacts.py`; test `tests/unit/test_locus_validation_artifacts.py`.

**Interfaces — produces:**

```python
SPEC_PATH: Final = "docs/superpowers/specs/2026-09-15-locus-policy-live-validation-design.md"
FINAL_SEAL_RULE: Final = "live HEAD must equal --frozen-sha; its single parent must equal harness_code_sha; parent..HEAD may add only manifest.json and expectations.json"
class Ceilings(FrozenModel): the six CEILING_KEYS fields
class ExperimentManifest(FrozenModel): experiment_version; artifact_format_version; harness_code_sha; baseline_sha; final_seal_rule; spec_path; spec_sha256; provider; model; reasoning_effort; grpc_dns_resolver; policy_version; prompt_sha256; historical_prompt_sha256s: dict[str,str]; output_schema_sha256; calls_per_delta; ledgers: tuple[LedgerSpec, ...] (id, project_id, scope, documents); evidence: tuple[EvidenceRecord, ...]; corpus_sha256; leakage_needle_set_sha256; expectations_sha256; ceilings; historical_preservation_base_sha; historical_artifact_dirs; historical_artifact_tree_hashes; predecessor_raw_run_sha; predecessor_adjudication_sha; raw_artifact_paths: tuple[str, ...]
def build_manifest(*, harness_code_sha: str, spec_sha256: str, historical_tree_hashes: Mapping[str, str]) -> ExperimentManifest   # exactly the seven dirs, 40-hex, else ValueError; built only from frozen constants, corpus.evidence_records(), corpus.corpus_sha256(), leakage.needle_set_sha256(), canonical_sha256(expectations_document())
def write_preregistration(out_dir: Path, manifest) -> dict[str, str]   # exactly manifest.json + expectations.json; all-or-nothing refusal if either exists
RAW_ARTIFACT_PATHS: Final = ("consumption.json","preflight.json","measurements.json","verdicts.json","report.md", *(f"L-{l}/{n}.json" for l in ("alpha","beta") for n in ("requests","drafts","receipts","decisions","ledger","state_T1","state_T2","result")))   # 21
CONSUMPTION_PATHS: Final = ("consumption.json", "preflight.json")
def existing_raw_artifacts(out_dir: Path) -> tuple[str, ...]
def write_consumption(out_dir: Path, *, gates: tuple[GateResult, ...], frozen_sha: str, harness_code_sha: str, leakage: LeakageResult, observed_grpc_dns_resolver: str | None, consumed_at: datetime) -> tuple[Path, Path]   # THE identity-consuming write: refuses (nothing written) if any raw artifact exists; writes preflight.json (gates, all_passed True required — refuses otherwise, leakage, resolver, frontier_calls 0) and consumption.json (seal sha, harness sha, policy version, prompt sha, model config, consumed_at; NEVER a key or secret-shaped value) atomically (temp + rename, consumption last)
def write_run_artifacts(out_dir: Path, run: RunResult, verdicts: tuple[IntegrityVerdict, ...], case_results: tuple[CaseResult, ...]) -> tuple[str, ...]   # the other 19 paths; write-once (refuse if any of the 19 exists; consumption.json/preflight.json MUST already exist — else refuse); requests.json entries {"record", "reference_snapshot"} bound on (arm, t, call_number, request_sha256); NOT_RUN ledgers get all eight files; secret-shaped scientific request text refuses the whole write; redact_secrets only on diagnostics; verdicts.json: {"phase": "raw", "status", "error", "budget", "integrity": {L1..L9 with failed_ledgers}, "case_assertions": [CaseResult dumps], "semantic_assertions": null, "semantic_notes": null, "case_outcomes": null, "experiment_outcome": null (or "EXPERIMENT_INCONCLUSIVE" only when rule 0 already holds from status/L-verdicts — and case_outcomes still null)}; report.md contains the literal line "experiment_outcome = null (architect adjudication pending)" unless rule 0 already recorded INCONCLUSIVE; the writer never references LOCUS_POLICY_VALIDATED/NOT_VALIDATED
class Adjudication(FrozenModel): semantic_answers: dict[Ledger, dict[str, bool]]   # exactly SEMANTIC_ASSERTION_IDS per ledger; notes: str
class AdjudicationRefused(RuntimeError)
def write_adjudication(out_dir: Path, *, raw_run_commit_sha: str, git: GitCliLike, adjudication: Adjudication, repo_root: Path, env: Mapping[str, str]) -> tuple[str, ...]   # refuses unless git.head() == raw_run_commit_sha, git.dirty() == "", every one of the 21 raw files exists and equals git.show_bytes(raw sha, repo-relative path), "XAI_API_KEY" not in env (presence-only; value never read), phase == "raw"; computes case outcomes (§14) and experiment_outcome via expectations.experiment_outcome(rule_zero=<status != COMPLETED or any L1..L8 failed>, case_passes=…); rewrites ONLY verdicts.json (raw entries semantically unchanged; fills semantic_assertions, semantic_notes, case_outcomes, experiment_outcome, phase "adjudicated") and report.md; proves the other 19 files byte-identical afterwards; write-once (phase already adjudicated → refuse)
```

- [ ] **Step 1: Tests (RED)** — manifest: canonical hash stable across mapping insertion order; `expectations_sha256 == canonical_sha256(expectations_document())`; `corpus_sha256 == corpus.corpus_sha256()`; seven dirs exactly, else ValueError (missing/extra/malformed); `raw_artifact_paths == RAW_ARTIFACT_PATHS` (21); preregistration exactly two files, all-or-nothing refusal; **consumption**: refuses when any raw artifact exists, refuses when `all_passed` is False, writes exactly the two files, `consumption.json` carries no `XAI`/key/secret-shaped text even when passed a poisoned environment-like string in diagnostics; **raw write**: refuses when consumption files are absent (a raw tree can never exist without a consumption record); write-once all-or-nothing (stray `L-beta/ledger.json` → refusal, digests unchanged); scripted COMPLETED run → exactly the 21 paths, 8 request pairs bound exactly, NOT_RUN β on an aborted run still yields its eight files; measurements 8 rows; verdicts.json semantic fields null and `experiment_outcome` null on a clean run, `"EXPERIMENT_INCONCLUSIVE"` with `case_outcomes` null on an aborted run; report pending line; AST + monkeypatch proof that `write_run_artifacts`/`write_consumption` never call `expectations.experiment_outcome` and never contain the VALIDATED tokens; secret-shaped rendered request refuses the whole write; diagnostic secret redacted; **adjudication**: HEAD mismatch / dirty / one differing raw byte / missing raw file / `XAI_API_KEY` present in env / phase already adjudicated → `AdjudicationRefused`, nothing written; success changes exactly `verdicts.json` + `report.md` (19 others byte-identical, proven by digest); case outcomes: all structural pass + all answers True → `LOCUS_POLICY_VALIDATED`; one False answer → `NOT_VALIDATED` naming the case; one structural fail → `NOT_VALIDATED` with tags; rule 0 (aborted status or an L-failure) → `INCONCLUSIVE` regardless of answers; answers for V04 or an unknown id → validation error; missing a ledger → validation error.
- [ ] **Step 2: RED. Step 3: Implement. Step 4: GREEN + checks + commit.**

---

## T8 — Entry points: prepare, run (preflight-only / live), adjudicate

**Commit:** `experiment: add locus validation entrypoints`

**Files:** create `scripts/prepare_locus_validation.py`, `scripts/run_locus_validation.py`, `scripts/adjudicate_locus_validation.py`; test `tests/integration/test_locus_validation_entrypoint.py`.

**Prepare** (`main(argv, *, cwd, git=None) -> int`; default `--out docs/superpowers/experiments/2026-09-15-locus-validation-v1`): allowed git argv in order — `status --porcelain` (empty), `rev-parse HEAD`, `merge-base --is-ancestor <BASELINE_SHA> HEAD`, `merge-base --is-ancestor <DESIGN_BASE_SHA> HEAD`, `merge-base --is-ancestor <PREDECESSOR_ADJUDICATION_SHA> HEAD`, `show HEAD:<SPEC_PATH>` (== working-tree bytes), per historical dir `rev-parse <DESIGN_BASE_SHA>:<dir>` and `rev-parse HEAD:<dir>` (equal, else refuse); refuse if either prereg file exists; `build_manifest`; `write_preregistration`; print the two canonical hashes; refusals `REFUSED: …` exit 2 with nothing written. No key, no reasoner, no network.

**Run** (`main(argv, *, cwd, env, reasoner_factory, git) -> int`; exit codes 0 / 2 refused / 3 preflight failed / 4 aborted after consumption):
- `--preflight-only --frozen-sha <40hex> --out <dir>`: read the seal files (refuse → 2), resolver once, real leakage gate, real 18 gates, print the preflight document (gates, `all_passed`, `frontier_calls: 0`, resolver); **write nothing, construct nothing, never read the key, never consume**; exit 0/3; repeatable.
- `--live`: args → seal files → **complete preflight from scratch** (never trusting an earlier run) → any failed gate: exit 3, nothing written, not consumed → `env.get("XAI_API_KEY")` missing/empty → `REFUSED`, exit 2, nothing written, not consumed → `default_reasoner_factory(api_key=…) -> XAILocusSemanticReasoner(api_key, model=MODEL, reasoning_effort=REASONING_EFFORT)`; `del api_key`; `require_locus_identity(inner)` → drift: `REFUSED`, exit 2, nothing written, not consumed → **`write_consumption(...)` (identity consumed; the only write before the first call)** → `run_experiment` inside one abort-recording `try` (KeyboardInterrupt and Exception recorded, never retried) → `case_results = evaluate_run(run)`; `verdicts = integrity_verdicts(run, preflight_gates=<the exact gate tuple written to preflight.json>, case_results=…)` → `write_run_artifacts` exactly once; a preservation failure after consumption → redacted `RAW ARTIFACT PRESERVATION FAILED`, exit 4, no second write, no replacement run → exit 0 iff `run.status is COMPLETED` else 4. A later `--live` with any raw artifact present refuses at the `no_raw_artifacts_exist` gate (exit 3 — the gate is the refusal; the factory is never called).
- `_aborted_result(...)` builds the `RunResult` for failures escaping the runner after consumption (both ledgers NOT_RUN/FAILED as recorded); never used before consumption.

**Adjudicate** (`main(argv, *, cwd, env, git=None) -> int`): `--raw-run-sha <40hex> --out <dir> --answers <json file> --notes <text>`; presence-only refusal if `XAI_API_KEY` in env; builds `Adjudication`; calls `write_adjudication`; prints the outcome; exit 0 / 2 refused.

- [ ] **Step 1: Tests (RED)** — FakeGit/FakePrepareGit/PoisonedEnv/scripted locus-identity reasoners; matrix: prepare success writes exactly two files using only the allowed argv before any write; each prepare refusal (dirty, non-ancestor ×3, spec differs, one tree differs, prereg exists); **preflight-only writes nothing and reads no key** (directory digest unchanged, `env.reads == ["GRPC_DNS_RESOLVER"]`, factory untouched), prints 18 gates, `frontier_calls: 0`, resolver variants fail only gate 15; **repeated preflight-only does not consume** (run three times: no file appears; a subsequent `--live` is NOT refused for raw artifacts); **failed preflight in `--live` does not consume** (dirty tree → exit 3, no files, key never read, factory never called; then fix the fake → live proceeds); **missing key does not consume** (exit 2, no files); **construction-time identity drift does not consume** (9p2-v1 fake as factory result → exit 2, no files, zero forwarded calls); **live consumes immediately before the first provider-call attempt**: an observing factory asserts `consumption.json` + `preflight.json` exist at the moment of the first `propose` and nothing else exists, and the fake's first call was not yet forwarded when they were written (order recorded); **provider failure after consumption**: exit 4, full 21-path tree, α partial preserved, β NOT_RUN, `verdicts.json.experiment_outcome == "EXPERIMENT_INCONCLUSIVE"`, `case_outcomes` null; a second `--live` → refused by `no_raw_artifacts_exist` (exit 3), factory never called; **SemanticOutputError after consumption**: same shape, ABORTED_MODEL_CONTRACT, no rerun; **raw artifacts make a second live impossible** even after a success; fake live success: 8 calls, both ledgers COMPLETED, 21 files, semantic fields null, exit 0; **8-call ceiling / 9th-call refusal**: a factory whose fake would answer a 9th call never receives it (the ceiling refuses before forwarding; with the scripted protocol the 9th call cannot even be requested — assert `frontier_calls == 8` and the fake saw 8); zero judges/retries/authorizations recorded; preservation failure after 8 calls → exit 4, one writer attempt, preflight/consumption untouched; manifest/expectations bytes unchanged across every mode; **adjudication end-to-end**: load the fake success tree into a FakeGit at a raw commit → `adjudicate` with all-True answers → `LOCUS_POLICY_VALIDATED`, only two files changed; with `XAI_API_KEY` present in env → refused; HEAD moved → refused; **historical 9P3 artifacts byte-identical**: the integration test snapshots the real `docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/` digests before and after every scenario; **pending model SUPERSEDE is never applied**: in the fake success the V05 supersede is `REQUIRE_SECOND_LENS` and absent from applied ids in `L-*/ledger.json`; the real experiment directory is never created (a repaired tripwire: prepare against the real default with a fake git must be refused only if the seal exists — before T10 it does not exist, so the test asserts the parser default and that no scenario touches it).
- [ ] **Step 2: RED** → `ModuleNotFoundError` for the three scripts. **Step 3: Implement** (mirror `scripts/prepare_long_horizon_bounded_memory.py` / `run_long_horizon_bounded_memory.py` shapes; `GitCli` with `tree_sha`; `_say` through `redact_secrets`). **Step 4: GREEN + `uv run ruff check` + `ruff format --check` on the three scripts + test; `MYPYPATH=src uv run mypy scripts/prepare_locus_validation.py scripts/run_locus_validation.py scripts/adjudicate_locus_validation.py`; commit.**

---

## T9 — Pre-seal qualification and whole-harness review (commit only for RED/GREEN fixes)

- [ ] Run, with `env -u XAI_API_KEY`: the full repository suite `uv run pytest -q -p no:cacheprovider` (record exact counts); the targeted suites `tests/unit/test_locus_validation_*.py tests/integration/test_locus_validation_entrypoint.py tests/unit/test_locus_policy.py tests/unit/test_compatible_extension_lifecycle.py tests/unit/test_admission.py tests/unit/test_long_horizon_bounded_*.py tests/integration/test_long_horizon_bounded_entrypoint.py tests/unit/test_contrastive_unseen_*.py tests/integration/test_contrastive_unseen_entrypoint.py`; `uv run ruff check .`; `uv run ruff format --check` on every file changed since `b34b987…`; `uv run mypy src`; `MYPYPATH=src uv run mypy` on the three scripts; `git diff --check`; `git status --short` empty.
- [ ] Diff gates: `git diff --name-only b34b987…..HEAD` = only the spec, this plan, `src/foundry/experiments/locus_validation/**`, the three scripts and the new tests; `git diff --name-only 1f89fc8…..HEAD -- src/foundry/domain src/foundry/application src/foundry/ports src/foundry/adapters` = exactly `src/foundry/adapters/semantics/xai_reasoner.py` and `src/foundry/domain/admission.py` (the locus policy, already qualified at `e0f5e42`) — nothing else; `git diff --name-only 3c30c16…..HEAD -- docs/superpowers/experiments src/foundry/experiments/long_horizon_bounded src/foundry/experiments/contrastive_unseen src/foundry/experiments/longitudinal` empty.
- [ ] In-process proofs: policy/prompt/schema hashes; historical prompt hashes; ceilings 8/0/0/0/0/2.00; corpus sha; needle sha; real leakage gate PASS over eight skeletons; request-path import gate PASS; `select`/outcome functions referenced only by `artifacts.write_adjudication`; `XAI_API_KEY` unset; no experiment directory exists.
- [ ] `superpowers:requesting-code-review` on `b34b987…..HEAD`: reuse boundary; request-path isolation; non-consuming preflight; consumption placement; abort preservation; raw/adjudication separation; 8-call ceiling; zero judge/retry/authorization; historical preservation; leakage; no provider call. Resolve Critical/Important via RED/GREEN + scoped re-review; re-run this whole block fresh afterwards. The post-review HEAD is the qualified `harness_code_sha`.

---

## T10 — Seal (T9-equivalent) and offline preflight, then STOP

**Seal commit:** `experiment: seal locus policy live validation v1`

- [ ] From the qualified, clean HEAD: presence-only `XAI_API_KEY` check (must be unset); `test ! -e docs/superpowers/experiments/2026-09-15-locus-validation-v1`.
- [ ] `uv run python scripts/prepare_locus_validation.py --out docs/superpowers/experiments/2026-09-15-locus-validation-v1` → exactly `manifest.json` + `expectations.json`; independent offline validation of every manifest field against in-process values (as in the 9P3 T9 script), `harness_code_sha == HEAD`, seven tree hashes == `git rev-parse <DESIGN_BASE_SHA>:<dir>` == HEAD trees, spec bytes == `git show HEAD:<SPEC_PATH>`.
- [ ] `git add` exactly the two files; commit; verify `HEAD^ == harness sha`, `git diff --name-only HEAD^..HEAD` == the two files, status clean, `manifest.harness_code_sha == HEAD^`.
- [ ] Offline preflight against the seal: `GRPC_DNS_RESOLVER=native uv run python scripts/run_locus_validation.py --preflight-only --frozen-sha <SEAL_SHA> --out <dir>` → exit 0, 18/18 PASS, nothing written (still two files, status clean); `env -u GRPC_DNS_RESOLVER … --preflight-only` → exit 3, only `grpc_dns_resolver_is_native` failed, nothing written. Run preflight-only a second time → still nothing written (non-consuming).
- [ ] STOP. Do not push. Live execution requires separate explicit human authorization after independent review of the seal.

---

## T11 — Live execution (separate authorization; exactly once)

- [ ] Verify HEAD == SEAL_SHA, clean, exactly two files; presence-only: `XAI_API_KEY` present and non-empty in the launching shell (never printed); pre-live check: no raw artifact.
- [ ] Launch **detached** (`nohup`, log outside the repository) exactly once: `GRPC_DNS_RESOLVER=native uv run python scripts/run_locus_validation.py --live --frozen-sha "$SEAL_SHA" --out "$OUT"`; record the exit code. Never rerun for any reason.
- [ ] After exit: `find "$OUT" -type f | wc -l` == 23 (2 seal + 21 raw) on any post-consumption outcome; `git diff --exit-code` on the two seal files; read-only summary from `preflight.json`/`measurements.json`/`verdicts.json` (18/18 gates, status, frontier_calls ≤ 8, cost ≤ 2.00, L1–L9, case assertion tags, semantic fields null, outcome null or INCONCLUSIVE).
- [ ] Raw freeze: `git add "$OUT"`; staged == exactly the 21 raw paths, seal files not staged; `git commit -m "experiment: record locus policy live validation v1 raw run"`; verify parent == SEAL_SHA, status clean. No adjudication, no push.

---

## T12 — Offline adjudication (separate authorization)

- [ ] From HEAD == RAW_RUN_SHA, clean, `XAI_API_KEY` unset: the architect answers `A-S01`, `A-V01`, `A-V02`, `A-V03`, `A-V05` per ledger (true/false) by reading only the frozen `L-*/drafts.json`, `L-*/state_T2.json`; writes the answers file outside the repo.
- [ ] `uv run python scripts/adjudicate_locus_validation.py --raw-run-sha "$RAW_RUN_SHA" --out "$OUT" --answers <file> --notes "<text>"` → prints the outcome; `git status --short` shows exactly `verdicts.json` and `report.md`; commit `experiment: adjudicate locus policy live validation v1`; verify the other 19 raw files byte-identical (`git diff --name-only HEAD^..HEAD` == the two files). No push until the architect authorizes.

---

## Operator procedure (exact order)

1. **prepare** (T10): qualified clean HEAD → `prepare_locus_validation.py` → two files.
2. **seal** (T10): commit exactly the two files → `SEAL_SHA`; parent == qualified harness sha.
3. **preflight-only** (T10, repeatable): `--preflight-only --frozen-sha SEAL_SHA` → 18/18, nothing written, nothing consumed; may be repeated at any time before live.
4. **live** (T11, once, authorized): `--live --frozen-sha SEAL_SHA` → full preflight again → key → construction + identity guard → consumption write → 8 calls → evaluation + verdicts → raw tree; exit 0 or 4.
5. **raw freeze** (T11): commit exactly the 21 raw paths → `RAW_RUN_SHA`.
6. **adjudication** (T12, authorized): architect answers → `adjudicate_locus_validation.py` → commit exactly `verdicts.json` + `report.md` → `ADJUDICATION_SHA`.

## Plan self-review record

1. **Spec coverage:** §1–§3 → Global Constraints + T1 expectations; §4–§5 corpus → T1 (byte-exact transcription test); §6–§7.1 → T1 expectations + T4 evaluation; §7.2 → T1 `SEMANTIC_QUESTIONS` + T7 `Adjudication`; §8 gates 1–18 + L1–L9 → T5 (no test-suite gate; §8.1 → T9); §9 leakage → T6; §10 identity state machine → T2 recording (ceiling before forwarding), T7 `write_consumption` (the single consuming write, refused unless all gates passed and no raw artifact exists) and T8 (`--preflight-only` has no write path; `--live` re-preflights from scratch; failures before consumption write nothing); §11 raw/adjudication → T7 (`write_run_artifacts` requires the consumption record and leaves semantic fields null; `write_adjudication` guards and two-file boundary) + T11/T12; §12 ceilings → T2 protocol + recording (9th call refused before forwarding; cost check before forwarding); §13 → T7 `RAW_ARTIFACT_PATHS` (21) + T8; §14 scoring → T1 `experiment_outcome` (called only by `write_adjudication`); §15 abort → T3 fail-fast + T8 abort recording and preservation-failure law; §16 → T7 manifest; §17 → T2 constants + T5 gates 16–17 + T9 diff gates; §18 → T2/T3/T8 tests; §19–§20 → nothing beyond.
2. **Every required test in the architect's list has a home:** 8-call ceiling and 9th-call refusal before forwarding (T2, T8); zero judges/retries/authorizations (T2 constants without mutators, T5 L2/L6, T8); repeated preflight non-consuming, failed preflight non-consuming, consumption immediately before the first call (T8); provider failure and `SemanticOutputError` after consumption cannot be rerun (T8); raw artifacts make a second live impossible (T8); raw/adjudication separation and the two-file boundary (T7, T8); historical 9P3 artifacts byte-identical (T8 snapshot + T5 gates 16–17 + T9 diff gate); leakage gate (T6); request-only reference law (T2 snapshots + T5 L3); pending model SUPERSEDE never applied (T4 UNGOVERNED_SUPERSEDE, T5 L6, T8); both ledger state expectations (T4 correct-story tests + T8 fake success).
3. **No placeholders:** the only value not yet known is `DESIGN_BASE_SHA` — by construction the sha of the commit that adds this plan, which does not exist while the plan is written; T2 pastes it from git history and a test pins its 40-hex shape and that every historical dir exists in the tree. Everything else is literal in the spec or this plan.
4. **Interfaces consistent across tasks:** `Ledger`, `LedgerRecord`, `DeltaRecord`, `RunResult`, `RunStatus`, `CaseResult`, `IntegrityVerdict`, `LeakageResult`, `ExperimentManifest`, `Adjudication`, `GateResult`, `RequestRecord`, `RequestReferenceSnapshot` are named identically in every task that consumes them; `arm="F"` is fixed by Global Constraint 7.
5. **No production change:** the plan modifies nothing under the frozen paths; the locus policy behaviour is consumed as-is; any discovered defect is a STOP-and-report.
6. **No seal, no live call, no push** is scheduled before T10/T11 and each of those is a separately authorized step with its own operator checklist.
