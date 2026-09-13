# 9P3 Long-Horizon Bounded Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement, locally verify, preregister and seal the 9P3 long-horizon bounded-memory experiment that compares persistent contrastive memory (F), persistent non-contrastive memory (A) and fresh cumulative reconstruction (R) across the frozen 16-version × 12-locus Orion corpus — without any live provider call.

**Architecture:** Production Foundry stays frozen at `1f89fc86cda463da676bf45603b86a7dcb458452`. All 9P3 behaviour lives in a new experiment-only package `foundry.experiments.long_horizon_bounded` plus two scripts and tests. Arm F and Arm R run the frozen production `assimilate_delta`; Arm A runs the proven, unmodified 9P2 ablation `assimilate_ablation_delta`; every reasoner is wrapped by the unmodified 9P2 `RecordingReasoner`. The runner walks a fixed 48-cell schedule under one global budget; semantic grading and architecture selection happen only after the raw artifacts are committed.

**Tech Stack:** Python 3.12, Pydantic v2 frozen models, `fractions.Fraction` for exact rational thresholds, `decimal.Decimal` for cost, standard-library `ast`/`hashlib`/`json`/`pathlib`/`subprocess`, pytest, ruff, mypy (strict). Fakes and blocked sockets only.

**Spec:** `docs/superpowers/specs/2026-09-13-9p3-long-horizon-bounded-memory-design.md` (approved at `43e5ea60cd92b700db4c58314a5ce68c50028169`)

**Predecessor frozen 9P2 raw evidence:** `201198f60c51e16269451e7d582027361d7e8a24`

**Frozen 9P2 core:** `1f89fc86cda463da676bf45603b86a7dcb458452`

**Experiment version:** `intent-v2-long-horizon-bounded-memory-v1`

## Global Constraints

1. `FOUNDRY_CONSTITUTION.md`, `AGENTS.md` and the approved 9P3 spec outrank this plan. An architecturally material ambiguity is an `ARCHITECTURE QUESTION:` stop, not a guess.
2. **ZERO live provider/model/judge calls are authorized by this plan.** Never construct a real `XAISemanticReasoner`/`XAIContrastiveSemanticReasoner` in a test; never read a real `XAI_API_KEY`; never run `--live`. Every provider-adjacent test blocks sockets.
3. Toolchain is frozen: Python 3.12, Pydantic v2, pytest, ruff, mypy strict. Commands: `uv run pytest -q <files> -p no:cacheprovider`, `uv run ruff check <paths>`, `uv run ruff format --check <paths>`, `uv run mypy <paths>` (`MYPYPATH=src` for scripts).
4. Do not modify any file under `src/foundry/domain/`, `src/foundry/application/`, `src/foundry/ports/`, `src/foundry/adapters/`, `src/foundry/experiments/longitudinal/` or `src/foundry/experiments/contrastive_unseen/`. No PRE-EXISTING experiment artifact directory under `docs/superpowers/experiments/` may be modified (the six frozen directories are listed in T5 as `HISTORICAL_ARTIFACT_DIRS`; their trees at `HISTORICAL_PRESERVATION_BASE_SHA = 43e5ea60cd92b700db4c58314a5ce68c50028169` are the baseline). The NEW directory `docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/` may be created only at T9, and T9 may initially add only `manifest.json` and `expectations.json` to it. Do not modify the spec or this plan during execution.
5. New runtime code belongs only under `src/foundry/experiments/long_horizon_bounded/`; new scripts only `scripts/prepare_long_horizon_bounded_memory.py` and `scripts/run_long_horizon_bounded_memory.py`; new tests only the files in the File Map. No other file is created or modified before the seal; the seal adds exactly `manifest.json` and `expectations.json` under `docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/`.
6. Reuse, unmodified and by import: `foundry.experiments.contrastive_unseen.ablation.assimilate_ablation_delta` (Arm A), `foundry.experiments.contrastive_unseen.records.RecordingReasoner` and `RequestRecord` (exact request capture and reasoner identity checking), `foundry.application.incremental_assimilation.assimilate_delta` (Arms F and R). Do not create `long_horizon_bounded/ablation.py` or `long_horizon_bounded/records.py`; do not fork request rendering or identity checking.
7. Historical A identity: policy `intent-v2-9p-v4`, prompt SHA256 `24435801ae739a15f7ec405a23b9c431e26c5816a2e92de965e4041e7bd239e1`. Contrastive F/R identity: policy `intent-v2-9p2-v1`, prompt SHA256 `a68b969b6a408a7867e5d9805b364f470675f9b896f95b6f0147012e816d7410`. Output schema SHA256 for all arms: `ffc6946ad72c87bd0d3db25468f246a457a31932ed6854b90a0227a839f36851`. Provider `xai`, model `grok-4.6`, reasoning effort `high`, `GRPC_DNS_RESOLVER=native` supplied by the launcher (never set in Python).
8. Exactly 2 frontier calls per arm per version; 16 versions; 3 arms; 48 cells; 96 calls for a completed run. Ceilings: `max_frontier_calls = 96`, `max_judge_calls = 0`, `max_semantic_retries = 0`, `max_same_cell_reruns = 0`, `max_human_authorizations = 48`, `max_provider_cost_usd = 10.0`. No tools, search, retries, fallback, hidden judge, semantic repair or third frontier call.
9. Orion evidence bytes, ids, lineage, ordering, the hidden answer key, checkpoints C02–C16, transition classes, thresholds (25 % economy, 1.35 bounded growth, 1.50 R growth, 5 % F/A difference, early T2–T5, late T13–T16), the architecture-selection precedence and the needle set are scientific design (spec §4–§7, §10, §14, §16). Do not change them during implementation.
10. The experiment records structural facts only. It never decides semantic equivalence, whether a claim matches the answer key, whether two addresses denote one locus, or whether a subclaim is compatible; those remain architect adjudication after the raw freeze (spec §10.6). The live runner never computes architecture selection.
11. Hidden grading data (`expectations.py`) is never imported by a request-path module (`timeline.py`, `protocol.py`, `designation.py`, `authority.py`, `measurements.py`, `runner.py`) and never enters prompts, evidence, fixtures used by leakage skeletons, or request rendering.
12. Human authority is mechanical: pre-T structural snapshot of eligible targets, one AGREE per exactly-one-matching pending proposal, fail closed otherwise (spec §18). No human sees semantic correctness before agreeing.
13. Strict TDD per task: write the tests, run RED for the intended reason, minimum GREEN, targeted verification, commit with the exact message. Never weaken an invariant test to get green.
14. Any Critical/Important review finding is resolved with a new RED/GREEN cycle before continuing.
15. Do not push. Live execution requires a new explicit architect authorization after the seal is independently verified.

---

## File Map

New package (`src/foundry/experiments/long_horizon_bounded/`):

| File | Responsibility | Task |
|---|---|---|
| `__init__.py` | package docstring only | T1 |
| `timeline.py` | frozen model-visible Orion evidence (192 items), deltas, corpora, records, raw character counts | T1 |
| `protocol.py` | non-semantic schedule, budgets, project ids, authority checkpoint loci, provider/model constants | T1 |
| `expectations.py` | hidden answer key, checkpoints, thresholds, architecture-selection precedence; never in the request path | T1 |
| `designation.py` | mechanical 12-locus root designation | T2 |
| `authority.py` | pre-T eligible-target snapshots + mechanical AGREE | T2 |
| `measurements.py` | per-call measurements, totals, early/late means (exact rationals) | T3 |
| `runner.py` | 48-cell F/A/R runner, global budget, fail-fast | T4 |
| `leakage.py` | needle set, request skeletons, request-path import gate | T5 |
| `integrity.py` | I1–I15 deterministic gates + preflight | T5 |
| `artifacts.py` | manifest/expectations preregistration, write-once raw tree, post-freeze adjudication plumbing | T6 |

New scripts: `scripts/prepare_long_horizon_bounded_memory.py` (T7), `scripts/run_long_horizon_bounded_memory.py` (T7).

New tests: `tests/unit/test_long_horizon_bounded_timeline.py`, `_protocol.py`, `_expectations.py` (T1); `_designation.py`, `_authority.py` (T2); `_measurements.py` (T3); `_runner.py` (T4); `_leakage.py`, `_integrity.py` (T5); `_artifacts.py` (T6); `tests/integration/test_long_horizon_bounded_entrypoint.py` (T7).

Seal-only files (T9): `docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/manifest.json`, `.../expectations.json`.

Generic helpers imported read-only from the frozen 9P2 package (never modified): `contrastive_unseen.leakage.normalize_leakage_text`; `contrastive_unseen.integrity.CommandRunnerLike`, `GateResult`, `all_passed` (the 9P3 `GitCliLike` is declared in `long_horizon_bounded/integrity.py` because it adds `tree_sha(sha, path) -> str`; it is a superset of the 9P2 protocol: `head()`, `dirty()`, `parents(sha)`, `is_ancestor(a, d)`, `changed_paths(base, head)`, `show_bytes(sha, path)`, `tree_sha(sha, path)`); `contrastive_unseen.artifacts.canonical_bytes`, `canonical_sha256`, `pretty_json`; `longitudinal.artifacts.redact_secrets`, `contains_secret_shape`; `longitudinal.scoring.replay_matches`.

---

## T0 — Isolated workspace and baseline

No code change and no commit.

- [ ] Use `superpowers:using-git-worktrees` to create or verify an isolated worktree on `feat/intent-intelligence-v2`.
- [ ] Read in full: `FOUNDRY_CONSTITUTION.md`, `AGENTS.md`, the approved 9P3 spec, this plan, and the existing `src/foundry/experiments/contrastive_unseen/{ablation,records,runner,authority,integrity,artifacts}.py`, `scripts/prepare_contrastive_unseen_lifecycle.py`, `scripts/run_contrastive_unseen_lifecycle.py`.
- [ ] Verify the starting state:

```bash
git branch --show-current            # feat/intent-intelligence-v2
git rev-parse HEAD                   # must contain the approved design commit
git status --short                   # empty
git merge-base --is-ancestor 43e5ea60cd92b700db4c58314a5ce68c50028169 HEAD && echo design-ok
git merge-base --is-ancestor 1f89fc86cda463da676bf45603b86a7dcb458452 HEAD && echo core-ok
git merge-base --is-ancestor 201198f60c51e16269451e7d582027361d7e8a24 HEAD && echo 9p2-evidence-ok
```

- [ ] Baseline focused suite (must PASS; a failure is not 9P3 work — use `superpowers:systematic-debugging` and stop until understood):

```bash
uv run pytest -q -p no:cacheprovider \
  tests/unit/test_9p2_track_a_regression.py \
  tests/unit/test_contrastive_context.py \
  tests/unit/test_assimilation_context.py \
  tests/unit/test_incremental_assimilation.py \
  tests/unit/test_contrastive_unseen_ablation.py \
  tests/unit/test_contrastive_unseen_records.py \
  tests/unit/test_contrastive_unseen_authority.py \
  tests/unit/test_contrastive_unseen_integrity.py \
  tests/integration/test_contrastive_unseen_entrypoint.py
```

---

## T1 — Orion corpus, protocol and hidden scientific contract

**Commit:** `experiment: define 9P3 Orion contract`

**Files:**
- Create: `src/foundry/experiments/long_horizon_bounded/__init__.py`, `timeline.py`, `protocol.py`, `expectations.py`
- Test: `tests/unit/test_long_horizon_bounded_timeline.py`, `tests/unit/test_long_horizon_bounded_protocol.py`, `tests/unit/test_long_horizon_bounded_expectations.py`

**Interfaces — produces:**

```python
# timeline.py  (model-visible only; imports nothing from expectations/protocol)
Locus = Literal["A","B","C","D","E","F","G","H","I","J","K","L"]
LOCI: Final[tuple[Locus, ...]] = ("A","B","C","D","E","F","G","H","I","J","K","L")
EXPERIMENT_VERSION: Final = "intent-v2-long-horizon-bounded-memory-v1"
PROJECT_ID: Final = "PROJ-9P3-ORION"
SCOPE: Final = "orion-jobs"
SCOPE_TUPLE: Final = (SCOPE,)
VERSION_COUNT: Final[int] = 16
ARTIFACT_REFS: Final[dict[Locus, str]]           # spec §3 table, e.g. "orion/spec/A-execution-attempts.md"
DOCUMENT_ORDER: Final[dict[int, tuple[Locus, ...]]]   # spec §5.1: T1–T3 ABCDEFGHIJKL; T4–T12 ACBFGHDEKIJL; T13–T16 ACBFGHDEIJKL
SECTION_TEXT: Final[dict[tuple[int, Locus], str]]     # 192 entries; byte-exact spec §4/§5 texts
def evidence_id(t: int, locus: Locus) -> str          # f"EV-O-{locus}{t:02d}"
def observed_at(t: int, locus: Locus) -> datetime      # 2026-10-<t:02d>T00:<position:02d>:00Z
class LifecycleEvidence(FrozenModel): t: int; locus: Locus; item: EvidenceItem
TIMELINE: Final[tuple[LifecycleEvidence, ...]]        # 192, version order then document order
class EvidenceRecord(FrozenModel): t, locus, evidence_id, source_kind, source_ref, artifact_ref, supersedes_evidence_id, observed_at (ISO str), scope, content_sha256, content_bytes
def persistent_delta(t: int, *, project_id: str) -> tuple[EvidenceItem, ...]      # the 12 items of version t, document order
def reconstruction_corpus(t: int, *, project_id: str) -> tuple[EvidenceItem, ...] # all items of versions 1..t
def evidence_records() -> tuple[EvidenceRecord, ...]
def raw_evidence_character_count(t: int) -> int      # sum(len(item.content)) over reconstruction_corpus(t)
def corpus_sha256() -> str                           # canonical sha over evidence_records() dumps

# protocol.py  (non-semantic; imports timeline only)
Arm = Literal["F","A","R"]
ARM_ORDER_BY_T: Final[dict[int, tuple[Arm, Arm, Arm]]]   # spec §9 six-step rotation
ARM_SCHEDULE: Final[tuple[tuple[int, Arm], ...]]          # 48 positions
AUTHORITY_CHECKPOINTS: Final[dict[int, Locus]] = {3:"A",5:"B",7:"F",8:"B",10:"D",12:"G",14:"J",16:"I"}
MAX_FRONTIER_CALLS: Final[int] = 96; MAX_JUDGE_CALLS: Final[int] = 0; MAX_SEMANTIC_RETRIES: Final[int] = 0
MAX_SAME_CELL_RERUNS: Final[int] = 0; MAX_HUMAN_AUTHORIZATIONS: Final[int] = 48; MAX_COST_USD: Final = 10.0
PROVIDER: Final = "xai"; MODEL: Final = "grok-4.6"; REASONING_EFFORT: Final = "high"
GRPC_DNS_RESOLVER_ENV: Final = "GRPC_DNS_RESOLVER"; GRPC_DNS_RESOLVER_FROZEN: Final = "native"
FR_POLICY_VERSION: Final = "intent-v2-9p2-v1"; FR_PROMPT_SHA256: Final = "a68b969b…7410"
A_POLICY_VERSION: Final = "intent-v2-9p-v4"; A_PROMPT_SHA256: Final = "24435801…239e1"
OUTPUT_SCHEMA_SHA256: Final = "ffc6946a…6851"; FROZEN_CORE_SHA: Final = "1f89fc86cda463da676bf45603b86a7dcb458452"
PREDECESSOR_RAW_EVIDENCE_SHA: Final = "201198f60c51e16269451e7d582027361d7e8a24"
F_PROJECT_ID: Final = "PROJ-9P3-F"; A_PROJECT_ID: Final = "PROJ-9P3-A"
def r_project_id(t: int) -> str        # f"PROJ-9P3-R-T{t:02d}"
EARLY_WINDOW: Final = (2,3,4,5); LATE_WINDOW: Final = (13,14,15,16); MEASURED_WINDOW: Final = tuple(range(2,17))

# expectations.py  (hidden; may import timeline/protocol; never imported by request-path modules)
TransitionClass = Literal["RESTATEMENT","CORRECTION","REVERT","COMPATIBLE_EXTENSION","SEMANTIC_NO_OP"]
class Checkpoint(FrozenModel): id: str ("C02".."C16"); t: int; transition_class: TransitionClass; target_locus: Locus | None; expected_current_meaning: str; requirements: tuple[str, ...]; controls: tuple[Locus, ...]
CHECKPOINTS: Final[tuple[Checkpoint, ...]]   # 15 entries from spec §5/§6/§10.2
BASELINE_MEANINGS: Final[dict[Locus, str]]  # spec §4.13
CURRENT_MEANING_BY_T: Final[dict[int, dict[Locus, str]]]  # per version, per locus (spec §5 "Meaning" lines)
R_GRADING_RULES: Final[tuple[str, ...]]      # spec §10.4
GRADING_LABELS: Final[tuple[str, ...]]       # "C02".."C16","I1".."I15","errors_F","errors_A","errors_R", decision names
DECISION_NAMES: Final = ("SELECT_F","SELECT_A","REDESIGN_PERSISTENT_CONTEXT","SCALE_NOT_YET_PROVEN","INCONCLUSIVE_TIE","EXPERIMENT_INCONCLUSIVE")
ECONOMY_NUM, ECONOMY_DEN = 4, 3; BOUNDED_FACTOR = Fraction(135,100); R_GROWTH_FACTOR = Fraction(3,2); MEANINGFUL_DIFF = Fraction(5,100)
class SelectionInputs(FrozenModel): completed: bool; scientifically_valid: bool; errors_F: int; errors_A: int; errors_R: int; integrity_F: bool; integrity_A: bool; f_total: int; a_total: int; r_total: int; f_early_mean: str; f_late_mean: str; a_early_mean: str; a_late_mean: str; r_early_mean: str; r_late_mean: str   # means are exact Fraction strings "p/q"
class SelectionOutcome(FrozenModel): decision: str; matched_rule: str; predicates: dict[str, bool | str]; reason: str
def token_diff_fa(f_total: int, a_total: int) -> Fraction          # abs(F−A)/min(F,A)
def select_architecture(inputs: SelectionInputs) -> SelectionOutcome
def expectations_document() -> dict[str, Any]                        # canonical grading data
```

- [ ] **Step 1: Write the timeline tests (RED)** — `tests/unit/test_long_horizon_bounded_timeline.py` with an autouse socket-blocking fixture (copy the `_no_network` pattern from `tests/unit/test_contrastive_unseen_ablation.py`). Tests:

```python
SPEC = Path("docs/superpowers/specs/2026-09-13-9p3-long-horizon-bounded-memory-design.md")

def _spec_section_texts() -> list[str]:
    # test-time oracle only: the 38 fenced ```text blocks that begin with "## "
    return re.findall(r"```text\n(## .*?)```", SPEC.read_text(encoding="utf-8"), re.S)

def test_constants_are_locked():
    assert EXPERIMENT_VERSION == "intent-v2-long-horizon-bounded-memory-v1"
    assert PROJECT_ID == "PROJ-9P3-ORION" and SCOPE == "orion-jobs" and VERSION_COUNT == 16
    assert LOCI == tuple("ABCDEFGHIJKL")

def test_timeline_has_192_items_with_exact_ids_and_stable_artifact_refs():
    assert len(TIMELINE) == 192
    assert [e.item.evidence_id for e in TIMELINE][:3] == ["EV-O-A01", "EV-O-B01", "EV-O-C01"]
    for e in TIMELINE:
        assert e.item.artifact_ref == ARTIFACT_REFS[e.locus]
        assert e.item.scope == ("orion-jobs",) and e.item.project_id == PROJECT_ID

def test_180_lineage_edges_each_to_same_locus_previous_version():
    edges = [(e.t, e.locus, e.item.supersedes_evidence_id) for e in TIMELINE if e.item.supersedes_evidence_id]
    assert len(edges) == 180
    for t, locus, pred in edges:
        assert t >= 2 and pred == f"EV-O-{locus}{t-1:02d}"
    assert all(e.item.supersedes_evidence_id is None for e in TIMELINE if e.t == 1)

def test_document_order_regimes_and_observed_at():
    assert DOCUMENT_ORDER[1] == tuple("ABCDEFGHIJKL")
    assert DOCUMENT_ORDER[4] == tuple("ACBFGHDEKIJL") and DOCUMENT_ORDER[12] == DOCUMENT_ORDER[4]
    assert DOCUMENT_ORDER[13] == tuple("ACBFGHDEIJKL") and DOCUMENT_ORDER[16] == DOCUMENT_ORDER[13]
    assert observed_at(4, "C").isoformat() == "2026-10-04T00:01:00+00:00"   # C is position 1 at T4

def test_section_texts_are_byte_exact_to_the_spec_blocks():
    blocks = _spec_section_texts()
    assert len(blocks) == 38
    # block order in the spec: 0-11 = T1 (A..L), 12 = T2 C, 13 = T3 A, 14-25 = T4 (document order), 26-37 = T5..T16
    t1 = blocks[:12]; t4 = blocks[14:26]
    for locus, text in zip("ABCDEFGHIJKL", t1):
        assert SECTION_TEXT[(1, locus)] == text
    for locus, text in zip("ACBFGHDEKIJL", t4):
        assert SECTION_TEXT[(4, locus)] == text
    replacements = {2:"C", 3:"A", 5:"B", 6:"A", 7:"F", 8:"B", 9:"H", 10:"D", 11:"L", 12:"G", 13:"K", 14:"J", 15:"F", 16:"I"}
    single = [blocks[12], blocks[13]] + blocks[26:]   # T2, T3, then T5..T16 in order
    for (t, locus), text in zip(sorted(replacements.items()), single):
        assert SECTION_TEXT[(t, locus)] == text

def test_unchanged_sections_carry_forward_byte_identical():
    assert SECTION_TEXT[(2, "A")] == SECTION_TEXT[(1, "A")]
    assert SECTION_TEXT[(9, "B")] == SECTION_TEXT[(8, "B")]
    assert SECTION_TEXT[(16, "H")] == SECTION_TEXT[(9, "H")]

def test_t1_h_unchanged_and_t9_h_is_idempotent_repeat_cancellation():
    assert "no future execution attempt of that job may be started" in SECTION_TEXT[(1, "H")]
    t9 = SECTION_TEXT[(9, "H")]
    assert "3. If Orion receives a cancellation for a job that is already cancelled, the job must remain cancelled and the repeated cancellation must not otherwise change the job's state." in t9
    assert "never begin execution" not in t9

def test_every_section_at_most_1400_chars_and_no_grading_labels():
    forbidden = ("correction", "restatement", "revert", "no-op", "compatible extension", "expected", "lifecycle", "checkpoint", "SELECT_", "material error")
    for (t, locus), text in SECTION_TEXT.items():
        assert len(text) <= 1400, (t, locus)
        assert not any(w.lower() in text.lower() for w in forbidden), (t, locus)

def test_persistent_delta_and_reconstruction_corpus():
    assert [i.evidence_id for i in persistent_delta(4, project_id="X")] == [f"EV-O-{l}04" for l in "ACBFGHDEKIJL"]
    assert all(i.project_id == "X" for i in persistent_delta(4, project_id="X"))
    for t in range(1, 17):
        assert len(reconstruction_corpus(t, project_id="X")) == 12 * t
    ids = [i.evidence_id for i in reconstruction_corpus(16, project_id="X")]
    assert ids[:12] == [f"EV-O-{l}01" for l in "ABCDEFGHIJKL"] and ids[-1] == "EV-O-L16"

def test_evidence_records_hashes_and_raw_character_count():
    records = evidence_records()
    assert len(records) == 192
    for r in records:
        assert r.content_sha256 == hashlib.sha256(SECTION_TEXT[(r.t, r.locus)].encode()).hexdigest()
    assert raw_evidence_character_count(16) == sum(len(t) for t in SECTION_TEXT.values())
    assert raw_evidence_character_count(1) == sum(len(SECTION_TEXT[(1, l)]) for l in "ABCDEFGHIJKL")

def test_timeline_does_not_import_expectations_or_protocol():
    tree = ast.parse(Path(timeline_module.__file__).read_text())
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any("expectations" in m or "protocol" in m for m in mods)
```

- [ ] **Step 2: Write the protocol tests (RED)** — `tests/unit/test_long_horizon_bounded_protocol.py`:

```python
def test_arm_schedule_is_the_frozen_rotation():
    pattern = [("F","A","R"),("A","R","F"),("R","F","A"),("F","R","A"),("A","F","R"),("R","A","F")]
    for t in range(1, 17):
        assert ARM_ORDER_BY_T[t] == pattern[(t-1) % 6]
    assert len(ARM_SCHEDULE) == 48
    assert ARM_SCHEDULE[:3] == ((1,"F"),(1,"A"),(1,"R")) and ARM_SCHEDULE[-3:] == ((16,"F"),(16,"R"),(16,"A"))
    assert [t for t, _ in ARM_SCHEDULE] == sorted(t for t, _ in ARM_SCHEDULE)

def test_authority_checkpoints_and_budgets_are_exact():
    assert AUTHORITY_CHECKPOINTS == {3:"A",5:"B",7:"F",8:"B",10:"D",12:"G",14:"J",16:"I"}
    assert (MAX_FRONTIER_CALLS, MAX_JUDGE_CALLS, MAX_SEMANTIC_RETRIES, MAX_SAME_CELL_RERUNS, MAX_HUMAN_AUTHORIZATIONS, MAX_COST_USD) == (96, 0, 0, 0, 48, 10.0)
    assert 16 * 3 * 2 == MAX_FRONTIER_CALLS

def test_identities_match_the_frozen_adapter():
    from foundry.adapters.semantics import xai_reasoner as x
    assert FR_POLICY_VERSION == x.CONTRASTIVE_POLICY_VERSION == "intent-v2-9p2-v1"
    assert A_POLICY_VERSION == x.POLICY_VERSION == "intent-v2-9p-v4"
    assert FR_PROMPT_SHA256 == hashlib.sha256(x.CONTRASTIVE_SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert A_PROMPT_SHA256 == hashlib.sha256(x.SYSTEM_INSTRUCTION.encode()).hexdigest()
    assert OUTPUT_SCHEMA_SHA256 == x.semantic_output_schema_sha256()
    assert (PROVIDER, MODEL, REASONING_EFFORT, GRPC_DNS_RESOLVER_FROZEN) == ("xai", "grok-4.6", "high", "native")

def test_project_ids_and_windows():
    assert (F_PROJECT_ID, A_PROJECT_ID, r_project_id(7)) == ("PROJ-9P3-F", "PROJ-9P3-A", "PROJ-9P3-R-T07")
    assert EARLY_WINDOW == (2,3,4,5) and LATE_WINDOW == (13,14,15,16) and MEASURED_WINDOW == tuple(range(2,17))

def test_protocol_does_not_import_expectations():  # ast scan as in the timeline test
```

- [ ] **Step 3: Write the expectations tests (RED)** — `tests/unit/test_long_horizon_bounded_expectations.py`:

```python
def test_checkpoints_c02_to_c16_with_classes_and_targets():
    assert [c.id for c in CHECKPOINTS] == [f"C{t:02d}" for t in range(2, 17)]
    classes = {c.t: (c.transition_class, c.target_locus) for c in CHECKPOINTS}
    assert classes[2] == ("RESTATEMENT","C") and classes[3] == ("CORRECTION","A") and classes[4] == ("SEMANTIC_NO_OP", None)
    assert classes[8] == ("REVERT","B") and classes[9] == ("COMPATIBLE_EXTENSION","H") and classes[13] == ("RESTATEMENT","K")
    assert {t for t, (k, _) in classes.items() if k == "CORRECTION"} == {3,5,7,10,12,14,16}
    for c in CHECKPOINTS:
        assert c.controls == tuple(l for l in LOCI if l != c.target_locus)

def test_current_meaning_by_t_tracks_the_answer_key():
    assert "three" in BASELINE_MEANINGS["A"].lower() and CURRENT_MEANING_BY_T[1] == BASELINE_MEANINGS
    assert "4 total" in CURRENT_MEANING_BY_T[3]["A"] and CURRENT_MEANING_BY_T[6]["A"] == CURRENT_MEANING_BY_T[3]["A"]
    assert "exponential" in CURRENT_MEANING_BY_T[5]["B"].lower() and "fixed 5" in CURRENT_MEANING_BY_T[8]["B"]
    assert CURRENT_MEANING_BY_T[16]["N" if False else "I"] != CURRENT_MEANING_BY_T[15]["I"]

def test_token_diff_fa_is_symmetric_with_cheaper_denominator():
    assert token_diff_fa(100, 88) == Fraction(12, 88) == token_diff_fa(88, 100)
    assert token_diff_fa(100, 100) == 0

def _inputs(**kw):  # completed valid run with all-zero errors, bounded, economical by default
    base = dict(completed=True, scientifically_valid=True, errors_F=0, errors_A=0, errors_R=0, integrity_F=True, integrity_A=True,
                f_total=100, a_total=100, r_total=200, f_early_mean="10/1", f_late_mean="11/1", a_early_mean="10/1", a_late_mean="11/1",
                r_early_mean="10/1", r_late_mean="16/1")
    base.update(kw); return SelectionInputs(**base)

def test_binding_examples_from_spec_16_4():
    assert select_architecture(_inputs(errors_F=1, a_total=103)).decision == "SELECT_A"                      # ex 1
    assert select_architecture(_inputs(errors_F=1, a_total=103, a_late_mean="20/1")).decision == "REDESIGN_PERSISTENT_CONTEXT"
    assert select_architecture(_inputs(a_total=88)).decision == "SELECT_A"                                    # ex 2 (12 % cheaper)
    assert select_architecture(_inputs(f_total=98)).decision == "INCONCLUSIVE_TIE"                            # ex 3 (2 % cheaper)
    assert select_architecture(_inputs(errors_A=1, a_total=60, f_total=100)).decision == "SELECT_F"          # ex 4
    assert select_architecture(_inputs(f_total=190, a_total=190, r_late_mean="12/1")).decision == "SCALE_NOT_YET_PROVEN"  # ex 5

def test_exhaustive_predicate_classification_and_errors_r_is_irrelevant():
    for accF, accA, bF, bA, eF, eA, rg in itertools.product([False, True], repeat=7):
        for f_total, a_total in ((100,100),(100,103),(103,100),(100,120),(120,100)):
            inputs = _inputs(errors_F=0 if accF else 1, errors_A=0 if accA else 1,
                             f_late_mean="11/1" if bF else "20/1", a_late_mean="11/1" if bA else "20/1",
                             f_total=f_total if eF else 200, a_total=a_total if eA else 200, r_total=200,
                             r_late_mean="16/1" if rg else "12/1")
            out = select_architecture(inputs)
            assert out.decision in DECISION_NAMES and out.matched_rule != "residual"
            assert not (out.decision == "SELECT_F" and not accF) and not (out.decision == "SELECT_A" and not accA)
            for r_err in (0, 3):
                assert select_architecture(inputs.model_copy(update={"errors_R": r_err})).decision == out.decision

def test_invalid_or_incomplete_run_is_experiment_inconclusive_first():
    assert select_architecture(_inputs(completed=False)).decision == "EXPERIMENT_INCONCLUSIVE"
    assert select_architecture(_inputs(scientifically_valid=False, errors_F=1, errors_A=1)).matched_rule == "0"

def test_expectations_document_is_canonical_and_free_of_runtime_ids():
    doc = expectations_document()
    assert doc["experiment_version"] == EXPERIMENT_VERSION and doc["thresholds"]["bounded_factor"] == "27/20"
    assert "ADDR-" not in json.dumps(doc) and "CLAIM-" not in json.dumps(doc)
```

- [ ] **Step 4: Run RED**

```bash
uv run pytest -q tests/unit/test_long_horizon_bounded_timeline.py tests/unit/test_long_horizon_bounded_protocol.py tests/unit/test_long_horizon_bounded_expectations.py -p no:cacheprovider
```
Expected: collection `ImportError`/`ModuleNotFoundError` for the three missing modules.

- [ ] **Step 5: Implement `timeline.py`** — module docstring stating the law (model-visible bytes only; no grading semantics; no runtime parsing of the spec). Transcribe the 38 section texts byte-exactly from spec §4.1–§4.12 (T1), §5 T4 (twelve), and the 14 single-section replacements into a private `_T1`, `_T4` and `_REPLACEMENTS: dict[tuple[int, Locus], str]`; build `SECTION_TEXT` by carrying each locus forward version by version:

```python
def _materialize() -> dict[tuple[int, Locus], str]:
    texts: dict[tuple[int, Locus], str] = {}
    current = dict(_T1)
    for t in range(1, VERSION_COUNT + 1):
        if t == 4:
            current = dict(_T4)
        for locus, text in _REPLACEMENTS.get(t, {}).items():
            current[locus] = text
        for locus in LOCI:
            texts[(t, locus)] = current[locus]
    return texts
```

Build `TIMELINE` at import with `evidence_item(evidence_id=evidence_id(t, locus), project_id=PROJECT_ID, source_kind=SourceKind.DOCUMENT, source_ref=f"experiment://orion/T{t:02d}/{locus}", content=SECTION_TEXT[(t, locus)], observed_at=observed_at(t, locus), scope=SCOPE_TUPLE, artifact_ref=ARTIFACT_REFS[locus], supersedes_evidence_id=None if t == 1 else evidence_id(t-1, locus))`, iterating versions then `DOCUMENT_ORDER[t]`. `persistent_delta`/`reconstruction_corpus` use `item.model_copy(update={"project_id": project_id})` and raise `ValueError` for `t` outside 1..16.

- [ ] **Step 6: Implement `protocol.py` and `expectations.py`** — protocol constants exactly as the interface block; `ARM_SCHEDULE = tuple((t, arm) for t in range(1, 17) for arm in ARM_ORDER_BY_T[t])`. In `expectations.py`, `select_architecture` implements spec §16.2 literally:

```python
def select_architecture(inputs: SelectionInputs) -> SelectionOutcome:
    p = _predicates(inputs)   # acceptable_F/A, bounded_F/A, economy_F/A, r_grows, token_diff (str)
    def out(decision, rule, reason=""): return SelectionOutcome(decision=decision, matched_rule=rule, predicates=p, reason=reason)
    if not inputs.completed or not inputs.scientifically_valid:
        return out("EXPERIMENT_INCONCLUSIVE", "0", "operational or scientific invalidity")
    accF, accA = p["acceptable_F"], p["acceptable_A"]
    if not accF and not accA:
        return out("REDESIGN_PERSISTENT_CONTEXT", "1")
    if accF != accA:
        x = "F" if accF else "A"
        if p[f"bounded_{x}"] and p[f"economy_{x}"]: return out(f"SELECT_{x}", "2A")
        if not p[f"bounded_{x}"]: return out("REDESIGN_PERSISTENT_CONTEXT", "2B")
        return out("SCALE_NOT_YET_PROVEN" if not p["r_grows"] else "EXPERIMENT_INCONCLUSIVE", "2C")
    if not p["bounded_F"] and not p["bounded_A"]:
        return out("REDESIGN_PERSISTENT_CONTEXT", "3A")
    if p["bounded_F"] != p["bounded_A"]:
        x = "F" if p["bounded_F"] else "A"
        if p[f"economy_{x}"]: return out(f"SELECT_{x}", "3B")
        return out("SCALE_NOT_YET_PROVEN" if not p["r_grows"] else "EXPERIMENT_INCONCLUSIVE", "3B")
    if not p["economy_F"] and not p["economy_A"]:
        return out("SCALE_NOT_YET_PROVEN" if not p["r_grows"] else "EXPERIMENT_INCONCLUSIVE", "3C.a")
    if p["economy_F"] != p["economy_A"]:
        return out("SELECT_F" if p["economy_F"] else "SELECT_A", "3C.b")
    diff = token_diff_fa(inputs.f_total, inputs.a_total)
    if diff < MEANINGFUL_DIFF: return out("INCONCLUSIVE_TIE", "3C.c")
    return out("SELECT_F" if inputs.f_total < inputs.a_total else "SELECT_A", "3C.c")
```

`_predicates` computes `acceptable_X = errors_X == 0 and integrity_X`, `economy_X = 4*X_total <= 3*r_total`, `bounded_X = Fraction(late) <= BOUNDED_FACTOR * Fraction(early)`, `r_grows = Fraction(r_late) >= R_GROWTH_FACTOR * Fraction(r_early)`. `expectations_document()` returns `ExpectationsDocument(experiment_version=EXPERIMENT_VERSION, checkpoints=CHECKPOINTS, baseline_meanings=BASELINE_MEANINGS, current_meaning_by_t=CURRENT_MEANING_BY_T, r_grading_rules=R_GRADING_RULES, persistent_rubric=PERSISTENT_RUBRIC, integrity_titles=INTEGRITY_TITLES, grading_labels=GRADING_LABELS, thresholds=Thresholds(economy="4/3", bounded_factor="27/20", r_growth_factor="3/2", meaningful_diff="1/20", early_window=EARLY_WINDOW, late_window=LATE_WINDOW), selection_precedence=SELECTION_PRECEDENCE_TEXT, decision_names=DECISION_NAMES).model_dump(mode="json")` where `PERSISTENT_RUBRIC` is the spec §10.2 requirement text per class, `INTEGRITY_TITLES` the fifteen I-gate titles of spec §12, and `SELECTION_PRECEDENCE_TEXT` the §16.2 rule text verbatim.

- [ ] **Step 7: Run GREEN + checks**

```bash
uv run pytest -q tests/unit/test_long_horizon_bounded_timeline.py tests/unit/test_long_horizon_bounded_protocol.py tests/unit/test_long_horizon_bounded_expectations.py -p no:cacheprovider
uv run ruff check src/foundry/experiments/long_horizon_bounded tests/unit/test_long_horizon_bounded_timeline.py tests/unit/test_long_horizon_bounded_protocol.py tests/unit/test_long_horizon_bounded_expectations.py
uv run ruff format --check src/foundry/experiments/long_horizon_bounded
uv run mypy src/foundry/experiments/long_horizon_bounded
```
Expected: all pass; mypy clean.

- [ ] **Step 8: Commit**

```bash
git add src/foundry/experiments/long_horizon_bounded/__init__.py src/foundry/experiments/long_horizon_bounded/timeline.py src/foundry/experiments/long_horizon_bounded/protocol.py src/foundry/experiments/long_horizon_bounded/expectations.py tests/unit/test_long_horizon_bounded_timeline.py tests/unit/test_long_horizon_bounded_protocol.py tests/unit/test_long_horizon_bounded_expectations.py
git commit -m "experiment: define 9P3 Orion contract"
```

---

## T2 — Designation and pre-T authority

**Commit:** `experiment: add 9P3 designation and authority protocol`

**Files:**
- Create: `src/foundry/experiments/long_horizon_bounded/designation.py`, `authority.py`
- Test: `tests/unit/test_long_horizon_bounded_designation.py`, `tests/unit/test_long_horizon_bounded_authority.py`

**Interfaces — consumes:** `timeline.LOCI`, `timeline.Locus`, `timeline.evidence_id`; `protocol.MAX_HUMAN_AUTHORIZATIONS`; frozen `foundry.domain.semantic_view.derive_view`, `authority_record_is_live`; `foundry.domain.semantic_judgment.proposal_signature`, `SupersedeProposal`, `SemanticJudgment`, `ReasonerFingerprint`, `AdmissionRoute`; `foundry.domain.semantic.AuthorityRecord`; `SemanticGovernor.submit(judgment, *, human_actor_id: str | None = None) -> AdmissionDecision`, `SemanticGovernor.record_authority(record: AuthorityRecord) -> StoredEvent`.

**Interfaces — produces:**

```python
# designation.py
class RootDesignation(FrozenModel):
    locus: Locus; seed_evidence_id: str; status: Literal["DESIGNATED","UNDESIGNATED"]
    address_id: str | None; claim_ids: tuple[str, ...]; creating_judgment_ids: tuple[str, ...]; reason: str
def designate_seed_root(state: IntentState, *, locus: Locus, seed_evidence_id: str) -> RootDesignation
def designate_t1_roots(state: IntentState) -> dict[Locus, RootDesignation]   # seed = evidence_id(1, locus) for every locus

# authority.py
ARCHITECT_ACTOR: Final = "architect"
HUMAN_FINGERPRINT: Final = ReasonerFingerprint(provider="human", model="human://architect", policy_version="intent-v2-9p3-long-horizon-v1")
class AuthorizationOutcome(StrEnum): AGREED, NO_PROPOSAL, AMBIGUOUS_PROPOSALS, NOT_ELIGIBLE_NOT_AUTHORIZED
class EligibleTargets(FrozenModel):
    arm: Literal["F","A"]; t: int; target_locus: Locus; designated_address_id: str | None
    eligible_judgment_ids: tuple[str, ...]      # sorted created_by_judgment_ids of claims live at the address pre-T
    live_claim_ids: tuple[str, ...]; snapshot_sequence: int   # ledger length when snapshotted
class AuthorizationRecord(FrozenModel):
    arm; t; target_locus; target_judgment_id: str; outcome: AuthorizationOutcome; pending_judgment_ids: tuple[str, ...]
    submitted_judgment_id: str | None; proposal_signature: tuple[str, ...] | None; actor_id: Literal["architect"] = "architect"
class AuthorizationCeilingExceeded(RuntimeError)
class AuthorizationBudget(Protocol): human_authorizations: int
def record_architect_authority(governor, *, clock, id_factory) -> StoredEvent
def snapshot_eligible_targets(state: IntentState, *, arm, t, target_locus, designated_address_id: str | None, ledger_length: int) -> EligibleTargets
def authorize_eligible_supersessions(*, governor, eligible: EligibleTargets, pending_judgment_ids: tuple[str, ...], budget: AuthorizationBudget, clock, id_factory) -> tuple[AuthorizationRecord, ...]
```

- [ ] **Step 1: Write designation tests (RED)** — real `SemanticGovernor` over `InMemoryEventStore`, opaque fixtures (subject `SUBJECT_ALPHA`, predicate `PREDICATE_ALPHA`, never Orion text), builders copied from `tests/unit/test_contrastive_unseen_designation.py`. Tests: zero seed-supported claims → `UNDESIGNATED`/`NO_LIVE_SEED_SUPPORTED_CLAIM`; one address, one claim → `DESIGNATED`; one address, three seed-supported claims → all sorted claim/judgment ids; same seed across two addresses → `UNDESIGNATED`/`MULTIPLE_SEED_SUPPORTED_ADDRESSES`; `designate_t1_roots` returns all twelve keys using `EV-O-<locus>01` seeds; AST test that `designation.py` reads only `.address_id`, `.created_by_judgment_id` and `effective_evidence` (no `.predicate`, `.value`, `.subject`, `.facet`, `.content`).

- [ ] **Step 2: Write authority tests (RED)** — build a real ledger that models the B lineage: T1 claim `CLAIM_B1` at `ADDR_B` (judgment `J-b1`), then a model `ASSERT` of `CLAIM_B5` at `ADDR_B` plus a model `SUPERSEDE(J-b1)` AGREED by the harness (so `CLAIM_B1` is superseded and `CLAIM_B5` live). Tests:

```python
def test_t8_snapshot_contains_t5_claim_and_excludes_t1_claim():
    eligible = snapshot_eligible_targets(governor.state(), arm="F", t=8, target_locus="B", designated_address_id=ADDR_B, ledger_length=len(store.load(PROJECT)))
    assert eligible.eligible_judgment_ids == ("J-b5",) and "J-b1" not in eligible.eligible_judgment_ids

def test_snapshot_is_taken_before_ingesting_t_and_ignores_claims_created_during_t():  # assert claim after snapshot; snapshot unchanged

def test_several_eligible_claims_at_one_address_each_get_one_agree():   # two live claims, two pending proposals → two AGREED records

def test_exactly_one_matching_proposal_agrees_with_identical_signature_and_no_visible_evidence():
    # AGREE judgment: proposal_signature equal, visible_evidence_ids == (), reasoner == HUMAN_FINGERPRINT, route APPLY with "HUMAN_AUTHORITY"

def test_zero_matching_is_no_proposal_and_two_competing_is_ambiguous_with_no_write()

def test_non_eligible_pending_targets_are_recorded_not_authorized_and_never_retargeted()

def test_ceiling_allows_48th_and_refuses_49th_before_any_write():
    budget = _Budget(human_authorizations=47)
    records = authorize_eligible_supersessions(governor=governor, eligible=eligible, pending_judgment_ids=("J-sup",), budget=budget, clock=clock, id_factory=ids)
    assert [r.outcome for r in records] == [AuthorizationOutcome.AGREED] and budget.human_authorizations == 48
    budget = _Budget(human_authorizations=48)
    before = store.current_sequence(PROJECT)
    with pytest.raises(AuthorizationCeilingExceeded):
        authorize_eligible_supersessions(governor=governor2, eligible=eligible2, pending_judgment_ids=("J-sup2",), budget=budget, clock=clock, id_factory=ids)
    assert store.current_sequence(PROJECT) == before and budget.human_authorizations == 48

def test_no_semantic_inspection_in_authority_source():  # AST: no access to .predicate/.value/.subject/.facet/.content/.rationale text of claims
def test_undesignated_locus_authorizes_nothing()
```

- [ ] **Step 3: Run RED** — `uv run pytest -q tests/unit/test_long_horizon_bounded_designation.py tests/unit/test_long_horizon_bounded_authority.py -p no:cacheprovider`. Expected: `ImportError` on the two modules.

- [ ] **Step 4: Implement `designation.py`** — same algorithm as 9P2 (`derive_view(state.semantic).effective_evidence` keyed by live claims; collect claim ids containing the seed; map to `claims[id].address_id`; reasons exactly `NO_LIVE_SEED_SUPPORTED_CLAIM` / `MULTIPLE_SEED_SUPPORTED_ADDRESSES`; `DESIGNATED` with sorted claim ids and sorted-deduplicated `created_by_judgment_id`s). `designate_t1_roots` loops `LOCI`.

- [ ] **Step 5: Implement `authority.py`**

```python
def snapshot_eligible_targets(state, *, arm, t, target_locus, designated_address_id, ledger_length):
    if designated_address_id is None:
        return EligibleTargets(arm=arm, t=t, target_locus=target_locus, designated_address_id=None,
                               eligible_judgment_ids=(), live_claim_ids=(), snapshot_sequence=ledger_length)
    view = derive_view(state.semantic)
    live = sorted(cid for cid in view.effective_evidence if state.semantic.claims[cid].address_id == designated_address_id)
    judgments = tuple(sorted({state.semantic.claims[cid].created_by_judgment_id for cid in live}))
    return EligibleTargets(arm=arm, t=t, target_locus=target_locus, designated_address_id=designated_address_id,
                           eligible_judgment_ids=judgments, live_claim_ids=tuple(live), snapshot_sequence=ledger_length)

def _model_supersede_targets(state: IntentState, pending_judgment_ids: tuple[str, ...]) -> dict[str, list[str]]:
    """target_judgment_id -> sorted pending judgment ids, for model-originated SUPERSEDE proposals only."""
    targets: dict[str, list[str]] = {}
    for pending_id in sorted(pending_judgment_ids):
        judgment = state.semantic.judgments[pending_id]          # unknown id raises KeyError: caller-contract error, never repaired
        proposal = judgment.proposal
        if isinstance(proposal, SupersedeProposal) and not judgment.reasoner.is_human:
            targets.setdefault(proposal.target_judgment_id, []).append(pending_id)
    return targets

def _record(eligible: EligibleTargets, *, target: str, outcome: AuthorizationOutcome, pending: tuple[str, ...] = (),
            submitted: str | None = None, signature: tuple[str, ...] | None = None) -> AuthorizationRecord:
    return AuthorizationRecord(arm=eligible.arm, t=eligible.t, target_locus=eligible.target_locus, target_judgment_id=target,
                               outcome=outcome, pending_judgment_ids=pending, submitted_judgment_id=submitted,
                               proposal_signature=signature)

def authorize_eligible_supersessions(*, governor, eligible, pending_judgment_ids, budget, clock, id_factory):
    targets = _model_supersede_targets(governor.state(), pending_judgment_ids)
    records: list[AuthorizationRecord] = []
    for target in eligible.eligible_judgment_ids:                       # already sorted by the snapshot
        pending = tuple(targets.get(target, []))
        if not pending:
            records.append(_record(eligible, target=target, outcome=AuthorizationOutcome.NO_PROPOSAL)); continue
        if len(pending) > 1:
            records.append(_record(eligible, target=target, outcome=AuthorizationOutcome.AMBIGUOUS_PROPOSALS, pending=pending)); continue
        if budget.human_authorizations >= MAX_HUMAN_AUTHORIZATIONS:
            raise AuthorizationCeilingExceeded(
                f"human authorization ceiling {MAX_HUMAN_AUTHORIZATIONS} reached before AGREE on {pending[0]}; nothing was written")
        pending_judgment = governor.state().semantic.judgments[pending[0]]
        submitted = _submit_agreement(governor, pending_judgment, clock=clock, id_factory=id_factory)
        # _submit_agreement (same shape as contrastive_unseen.authority): pre-check a live project-wide AuthorityRecord for
        # "human://architect"; build SemanticJudgment(proposal=pending_judgment.proposal, visible_evidence_ids=(),
        # rationale=f"AGREE: {pending_judgment.judgment_id}", reasoner=HUMAN_FINGERPRINT, invocation_id=id_factory("authorization"),
        # proposed_at=clock(), judgment_id=id_factory("judgment"), project_id=pending_judgment.project_id);
        # decision = governor.submit(judgment, human_actor_id="human://architect");
        # post-check route APPLY and "HUMAN_AUTHORITY" in reasons, else raise RuntimeError. Returns the AGREE judgment id.
        budget.human_authorizations += 1
        records.append(_record(eligible, target=target, outcome=AuthorizationOutcome.AGREED, pending=pending,
                               submitted=submitted, signature=proposal_signature(pending_judgment.proposal)))
    for target, pending_ids in sorted(targets.items()):
        if target not in eligible.eligible_judgment_ids:
            for pending_id in pending_ids:
                records.append(_record(eligible, target=target, outcome=AuthorizationOutcome.NOT_ELIGIBLE_NOT_AUTHORIZED, pending=(pending_id,)))
    return tuple(records)
```

- [ ] **Step 6: GREEN + checks** — the two test files; `ruff check`/`ruff format --check` on the two modules and tests; `mypy src/foundry/experiments/long_horizon_bounded`.

- [ ] **Step 7: Commit**

```bash
git add src/foundry/experiments/long_horizon_bounded/designation.py src/foundry/experiments/long_horizon_bounded/authority.py tests/unit/test_long_horizon_bounded_designation.py tests/unit/test_long_horizon_bounded_authority.py
git commit -m "experiment: add 9P3 designation and authority protocol"
```

---

## T3 — Measurements and the reuse boundary

**Commit:** `experiment: add 9P3 measurement contract`

**Files:**
- Create: `src/foundry/experiments/long_horizon_bounded/measurements.py`
- Test: `tests/unit/test_long_horizon_bounded_measurements.py`

Do **not** create `long_horizon_bounded/ablation.py` or `records.py`; the reuse boundary is `from foundry.experiments.contrastive_unseen.ablation import assimilate_ablation_delta` and `from foundry.experiments.contrastive_unseen.records import RecordingReasoner, RequestRecord`.

**Interfaces — produces:**

```python
class CallMeasurement(FrozenModel):
    arm: Arm; t: int; call_number: Literal[1, 2]
    input_tokens: int; output_tokens: int; provider_cost_usd: str   # Decimal as string
    wall_clock_ms: int; rendered_request_chars: int; known_address_count: int; known_claim_count: int
    comparison_context_chars: int
    r_cumulative_raw_evidence_chars: int | None   # R: exactly raw_evidence_character_count(t); F/A: None (not applicable — never 0)
    request_sha256: str; invocation_id: str
class TokenSummary(FrozenModel):
    f_total: int; a_total: int; r_total: int          # T2..T16 input tokens
    f_early_mean: str; f_late_mean: str; a_early_mean: str; a_late_mean: str; r_early_mean: str; r_late_mean: str  # Fraction "p/q"
    per_arm_per_t: dict[str, dict[int, int]]           # input tokens per arm per T (both calls)
class MeasurementMismatch(RuntimeError)
def measure_step(*, arm: Arm, t: int, records: tuple[RequestRecord, ...], receipts: tuple[Any, ...]) -> tuple[CallMeasurement, ...]
def summarize(measurements: tuple[CallMeasurement, ...]) -> TokenSummary
def window_mean(values: Iterable[int]) -> Fraction
```

- [ ] **Step 1: Tests (RED)** — with fake `RequestRecord`s and fake receipts (objects with `input_tokens`, `output_tokens`, `cost_usd`, `wall_clock_ms`, `invocation_id`): `measure_step` pairs record i with receipt i (call order) and copies fields exactly; `len(records) != len(receipts)` → `MeasurementMismatch` (fail closed, no partial output); `rendered_request_chars == len(record.rendered_user_request)`; A records must have `comparison_context_chars == 0` else `MeasurementMismatch`; R rows carry `r_cumulative_raw_evidence_chars == raw_evidence_character_count(t)` while F/A rows carry `None` (assert `is None`, never `== 0`), and the JSON dump of an F/A measurement serializes the field as `null`; `summarize` sums T2–T16 only (T1 excluded), computes `Fraction` means over `EARLY_WINDOW`/`LATE_WINDOW`, rejects a missing (arm, t) pair in the measured window; a test that `measurements.py` imports `RecordingReasoner`/`RequestRecord` from `contrastive_unseen.records` and that no module in `long_horizon_bounded` defines a class named `RecordingReasoner` or a function named `assimilate_ablation_delta` (AST scan of the package directory).

- [ ] **Step 2: Run RED** — `uv run pytest -q tests/unit/test_long_horizon_bounded_measurements.py -p no:cacheprovider` → `ImportError`.

- [ ] **Step 3: Implement** — exact rational arithmetic (`Fraction`), `Decimal(str(receipt.cost_usd))` for cost strings; no floats in comparisons.

- [ ] **Step 4: GREEN + checks + commit**

```bash
uv run pytest -q tests/unit/test_long_horizon_bounded_measurements.py -p no:cacheprovider
uv run ruff check src/foundry/experiments/long_horizon_bounded/measurements.py tests/unit/test_long_horizon_bounded_measurements.py
uv run mypy src/foundry/experiments/long_horizon_bounded
git add src/foundry/experiments/long_horizon_bounded/measurements.py tests/unit/test_long_horizon_bounded_measurements.py
git commit -m "experiment: add 9P3 measurement contract"
```

---

## T4 — 48-cell runner and global budgets

**Commit:** `experiment: implement 9P3 three-arm runner`

**Files:**
- Create: `src/foundry/experiments/long_horizon_bounded/runner.py`
- Test: `tests/unit/test_long_horizon_bounded_runner.py`

**Interfaces — consumes:** T1 `protocol` (schedule, budgets, ids, checkpoints), `timeline.persistent_delta`/`reconstruction_corpus`/`SCOPE`; T2 `designate_t1_roots`, `record_architect_authority`, `snapshot_eligible_targets`, `authorize_eligible_supersessions`, `AuthorizationCeilingExceeded`; T3 `measure_step`; reused `RecordingReasoner`, `assimilate_ablation_delta`; frozen `assimilate_delta`, `SemanticGovernor`, `InMemoryEventStore`, `replay_matches`, `XAIProviderError`, `SemanticOutputError`, `ContextUnsupported`.

**Interfaces — produces:**

```python
class RunStatus(StrEnum): NOT_RUN, ABORTED_PREFLIGHT, ABORTED_PROVIDER, ABORTED_MODEL_CONTRACT, ABORTED_RUNTIME, ABORTED_AUTHORITY_CEILING, ABORTED_BUDGET, COMPLETED
class ExperimentBudget:  # mutable
    frontier_calls: int = 0; provider_cost_usd: Decimal = Decimal("0"); human_authorizations: int = 0; judge_calls: int = 0
class ExperimentBudgetExceeded(RuntimeError)
class ReferenceSnapshotMismatch(RuntimeError)   # snapshot and RequestRecord disagree, or a forwarded call produced != 1 new RequestRecord

class RequestReferenceSnapshot(FrozenModel):
    """Experiment-only exact-request reference closure, captured from the very ReasoningRequest
    handed to the reused RecordingReasoner BEFORE it is forwarded; never rebuilt from later state."""
    arm: Arm
    t: int
    call_number: Literal[1, 2]
    request_sha256: str
    citable_evidence_ids: tuple[str, ...]
    known_address_ids: tuple[str, ...]
    known_claim_ids: tuple[str, ...]
    known_claim_creating_judgment_ids: tuple[str, ...]

def snapshot_request_references(request: ReasoningRequest) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Frozen capture rule, structural only, in request order."""
    return (
        tuple(item.evidence_id for item in request.evidence),
        tuple(address.address_id for address in request.known_addresses),
        tuple(claim.claim_id for claim in request.known_claims),
        tuple(claim.created_by_judgment_id for claim in request.known_claims),
    )

class BudgetedReasoner:
    """Wraps the reused RecordingReasoner. Two distinct moments must not be confused:
    RAW REFERENCE CAPTURE (the four id tuples are copied from the exact request object BEFORE delegation) and
    SNAPSHOT IDENTITY BINDING (the bound RequestReferenceSnapshot is appended in `finally`, AFTER the reused
    RecordingReasoner has supplied the RequestRecord identity). propose(request), frozen sequence:
    1. if budget.frontier_calls >= MAX_FRONTIER_CALLS: raise ExperimentBudgetExceeded (before forwarding);
    2. RAW REFERENCE CAPTURE, before delegation: refs = snapshot_request_references(request)  — copies evidence ids,
       known address ids, known claim ids and known-claim creating-judgment ids from the exact request object;
       records_before = len(recording.records); receipts_before = len(recording.receipts);
    3. budget.frontier_calls += 1; try: result = recording.propose(request)
       — the reused RecordingReasoner itself appends its RequestRecord and THEN delegates to inner.propose(request);
       nothing is appended to self._snapshots while inner.propose is running;
       finally:
         (a) new_records = recording.records[records_before:]; if len(new_records) != 1: raise ReferenceSnapshotMismatch
             (evaluated even when the provider raised — the RequestRecord exists because it was appended before delegation);
         (b) SNAPSHOT IDENTITY BINDING: append exactly one RequestReferenceSnapshot(arm=new_records[0].arm, t=new_records[0].t,
             call_number=new_records[0].call_number, request_sha256=new_records[0].request_sha256,
             citable_evidence_ids=refs[0], known_address_ids=refs[1], known_claim_ids=refs[2], known_claim_creating_judgment_ids=refs[3])
             to self._snapshots — this runs in `finally`, so it survives provider/model failure exactly as the RequestRecord does;
         (c) account every newly appended receipt exactly once into budget.provider_cost_usd (> 1 new receipt → RuntimeError("RECEIPT_INTEGRITY…"));
    4. after accounting: if budget.provider_cost_usd > Decimal(str(MAX_COST_USD)): raise ExperimentBudgetExceeded (judgments never reach governance);
    5. return result.
    Properties: recording, budget, snapshots (tuple[RequestReferenceSnapshot, ...]), fingerprint (delegates)."""
class ArmReasoners(NamedTuple): f: BudgetedReasoner; a: BudgetedReasoner; r: BudgetedReasoner
def build_arm_reasoners(*, inner_f, inner_a, inner_r, budget) -> ArmReasoners
class CellRecord(FrozenModel):
    arm: Arm; t: int; position: int (0..47); status: Literal["COMPLETED","FAILED","NOT_RUN"]; error: str | None; project_id: str
    evidence_ids_shown: tuple[str, ...]; requests: tuple[RequestRecord, ...]; reference_snapshots: tuple[RequestReferenceSnapshot, ...]
    stage_decisions: tuple[tuple[AdmissionDecision, ...], tuple[AdmissionDecision, ...]]; neighborhood: tuple[str, ...]; claim_neighborhood: tuple[str, ...]
    pending_supersede_judgment_ids: tuple[str, ...]; root_designations: tuple[RootDesignation, ...]; eligible_targets: EligibleTargets | None
    authorizations: tuple[AuthorizationRecord, ...]; measurements: tuple[CallMeasurement, ...]; receipts: tuple[Any, ...]; draft_payloads: tuple[Any, ...]
    state_snapshot: IntentState | None; view_snapshot: CurrentSemanticView | None; ledger: tuple[StoredEvent, ...]
class ArmSummary(FrozenModel): arm; project_id; roots: dict[Locus, RootDesignation]; ledger; final_state; final_view; replay: ReplayResult | None; eligible_targets: tuple[EligibleTargets, ...]; authorizations: tuple[AuthorizationRecord, ...]; requests: tuple[RequestRecord, ...]; reference_snapshots: tuple[RequestReferenceSnapshot, ...]
class RunResult(FrozenModel): status; error; cells: tuple[CellRecord, ...] (len 48); f: ArmSummary; a: ArmSummary; r_cells: dict[int, CellRecord]; budget: BudgetSnapshot; measurements: tuple[CallMeasurement, ...]; schedule
def run_reconstruction_step(*, t: int, position: int, reasoner: BudgetedReasoner, clock, id_factory) -> CellRecord   # constructs InMemoryEventStore() unlooped; position = index in ARM_SCHEDULE
def run_experiment(*, reasoners: ArmReasoners, clock, id_factory, progress: list[CellRecord] | None = None) -> RunResult
#   scheduler (frozen, full body in Step 3): `for position, (t, arm) in enumerate(ARM_SCHEDULE):` — every cell, persistent or R, carries that enumerated position;
#   arm == "R" → run_reconstruction_step(t=t, position=position, reasoner=reasoners.r, clock=clock, id_factory=id_factory);
#   arm in ("F", "A") → _run_persistent_step(session, t, position=position, clock=clock, id_factory=id_factory, budget=budget)
```

- [ ] **Step 1: Tests (RED)** — scripted reasoners (record requests; one batch per call; callable batches that inspect the real `ReasoningRequest`; raise-able batches; optional fake receipts with cost), fingerprints per arm (`intent-v2-9p2-v1` for F/R, `intent-v2-9p-v4` for A, model `grok-4.6`), sockets blocked. Prove: 48 COMPLETED cells and 96 requests on a scripted success; positions follow `ARM_SCHEDULE` exactly — `[(c.position, c.t, c.arm) for c in result.cells] == [(i, t, arm) for i, (t, arm) in enumerate(ARM_SCHEDULE)]` for all 48 cells, and specifically every R cell's `position` equals its index in `ARM_SCHEDULE` (`{c.position for c in result.cells if c.arm == "R"} == {i for i, (_, arm) in enumerate(ARM_SCHEDULE) if arm == "R"}`, 16 entries) with `result.r_cells[t].position` equal to that index; `run_reconstruction_step(t=3, position=6, ...)` called directly returns a cell with `position == 6`; F and A ledgers persist across T (T2 request shows T1-created addresses) while every R cell has a fresh store (`store.load` sequence starts at 1; project id `PROJ-9P3-R-T{t:02d}`; no prior claims visible); no cross-arm state (A's addresses never appear in F's requests); F/R Call 1 shows `known_claims` (production path) and A Call 1 shows none (ablation path); after F/A T1 all twelve roots are designated; at every checkpoint T the `eligible_targets` snapshot's `snapshot_sequence` equals the ledger length before ingestion and authority runs only after Call 2; no `eligible_targets`/authorizations at non-checkpoint T or for R; 97th call refused before forwarding; a receipt pushing cost past `Decimal("10.0")` is recorded and no later call happens (`ABORTED_BUDGET`); status classification per exception; first failure marks later cells NOT_RUN with no further calls; summarisation failure after the walk still returns a `RunResult` with all cells (`ABORTED_RUNTIME`, `replay=None`); replay equality for F and A on success; `runner.py` imports none of `expectations`, `leakage`, `integrity`, `artifacts` (AST) and defines no ablation/recording classes. Reference-snapshot tests — ordering by event log (no test may expect `reasoner.snapshots` to be populated while `inner.propose` is running; the bound snapshot is appended in `finally`):

```python
def test_raw_references_are_captured_before_inner_delegation_and_bound_after(monkeypatch):
    events: list[str] = []
    real_capture = runner_module.snapshot_request_references
    def spy_capture(request):
        events.append("RAW_REFERENCE_CAPTURE"); return real_capture(request)
    monkeypatch.setattr(runner_module, "snapshot_request_references", spy_capture)
    class Inner(ScriptedReasoner):
        def propose(self, request):
            events.append("INNER_DELEGATION"); return super().propose(request)
    inner = Inner([[]], fingerprint=FR_FINGERPRINT)
    budget = ExperimentBudget()
    wrapped = BudgetedReasoner(RecordingReasoner(inner, arm="F"), budget)
    wrapped.recording.begin_step(1)
    wrapped.propose(request)
    assert events == ["RAW_REFERENCE_CAPTURE", "INNER_DELEGATION"]
    assert len(wrapped.snapshots) == 1 and len(wrapped.recording.records) == 1
    snap, record = wrapped.snapshots[0], wrapped.recording.records[0]
    assert (snap.arm, snap.t, snap.call_number, snap.request_sha256) == (record.arm, record.t, record.call_number, record.request_sha256)

def test_provider_failure_keeps_exactly_one_record_and_one_bound_snapshot():
    inner = ScriptedReasoner([XAIProviderError("boom")], fingerprint=FR_FINGERPRINT)
    wrapped = BudgetedReasoner(RecordingReasoner(inner, arm="F"), ExperimentBudget())
    wrapped.recording.begin_step(1)
    with pytest.raises(XAIProviderError):
        wrapped.propose(request)
    assert len(wrapped.recording.records) == 1 and len(wrapped.snapshots) == 1
    assert wrapped.snapshots[0].request_sha256 == wrapped.recording.records[0].request_sha256
```

At run level: a scripted `XAIProviderError` at some position leaves that FAILED cell with exactly one `RequestRecord` and exactly one `RequestReferenceSnapshot` bound to it (same `arm`, `t`, `call_number`, `request_sha256`); a fake inner that appends two `RequestRecord`s (or none) for one call raises `ReferenceSnapshotMismatch`; every snapshot's `citable_evidence_ids`/`known_address_ids`/`known_claim_ids` equal the bound `RequestRecord`'s tuples exactly (same order); `known_claim_creating_judgment_ids[i]` is the creating judgment of `known_claim_ids[i]` in the request; F/A `ArmSummary.reference_snapshots` has 32 entries and each R cell has 2 on a completed run.

- [ ] **Step 2: Run RED** — `uv run pytest -q tests/unit/test_long_horizon_bounded_runner.py -p no:cacheprovider` → `ImportError`.

- [ ] **Step 3: Implement** — adapt `contrastive_unseen/runner.py` structure (one `try` site `_attempt`, `_StepCapture`, degrade ladder) to 48 positions. Persistent step:

```python
def run_experiment(*, reasoners, clock, id_factory, progress=None) -> RunResult:
    budget = _require_shared_budget(reasoners)
    f = _persistent_session("F", reasoners.f, clock=clock, id_factory=id_factory)   # store, governor PROJ-9P3-F, authority record, roots={}
    a = _persistent_session("A", reasoners.a, clock=clock, id_factory=id_factory)   # store, governor PROJ-9P3-A, authority record, roots={}
    cells: list[CellRecord] = []
    for position, (t, arm) in enumerate(ARM_SCHEDULE):          # the ONLY source of cell positions, 0..47
        if aborted:
            cells.append(_not_run(arm=arm, t=t, position=position, project_id=_project_id_for(arm, t))); continue
        if arm == "R":
            cell = _attempt(lambda: run_reconstruction_step(t=t, position=position, reasoner=reasoners.r, clock=clock, id_factory=id_factory), arm="R", t=t, position=position)
        else:
            session = f if arm == "F" else a
            cell = _attempt(lambda: _run_persistent_step(session, t, position=position, clock=clock, id_factory=id_factory, budget=budget), arm=arm, t=t, position=position)
        cells.append(cell)
        if progress is not None: progress.append(cell)
        if cell.status == "FAILED": aborted = True; status = _classify(cell_exception); error = cell.error
    return _summarise(status, error, cells, f, a, budget)          # summarisation under the same single catch site; degrades, never raises

def _run_persistent_step(session, t, *, position, clock, id_factory, budget) -> CellRecord:
    capture = _StepCapture(arm=session.arm, t=t, position=position, project_id=session.project_id,
                           store=session.store, governor=session.governor, reasoner=session.reasoner)
    eligible = None
    if t in AUTHORITY_CHECKPOINTS:
        locus = AUTHORITY_CHECKPOINTS[t]
        root = session.roots.get(locus)
        eligible = snapshot_eligible_targets(session.governor.state(), arm=session.arm, t=t, target_locus=locus,
                                             designated_address_id=root.address_id if root else None,
                                             ledger_length=session.store.current_sequence(session.project_id))
    delta = persistent_delta(t, project_id=session.project_id)
    session.reasoner.recording.begin_step(t)
    outcome = (assimilate_delta if session.arm == "F" else assimilate_ablation_delta)(governor=session.governor, reasoner=session.reasoner, delta=delta, scope=SCOPE)
    if t == 1:
        session.roots = designate_t1_roots(session.governor.state())
    authorizations: tuple[AuthorizationRecord, ...] = ()
    if eligible is not None:
        authorizations = authorize_eligible_supersessions(governor=session.governor, eligible=eligible, pending_judgment_ids=outcome.pending_supersede_judgment_ids, budget=budget, clock=clock, id_factory=id_factory)
    return capture.record(status="COMPLETED", error=None, outcome=outcome, eligible=eligible, authorizations=authorizations,
                          root_designations=tuple(session.roots.values()) if t == 1 else ())
```

Exact capture (`_StepCapture`, opened before ingestion with `attach(reasoner)` so that a FAILED cell still carries everything produced before the failure):

```python
class _StepCapture:
    def __init__(self, *, arm, t, position, project_id, store, governor, reasoner: BudgetedReasoner) -> None:
        self.arm, self.t, self.position, self.project_id, self.store, self.governor, self.reasoner = arm, t, position, project_id, store, governor, reasoner
        rec = reasoner.recording
        self._records_before, self._snapshots_before = len(rec.records), len(reasoner.snapshots)
        self._receipts_before, self._drafts_before = len(rec.receipts), len(rec.draft_payloads)

    def record(self, *, status, error, outcome=None, eligible=None, authorizations=(), root_designations=()) -> CellRecord:
        rec = self.reasoner.recording
        requests = rec.records[self._records_before:]                      # this cell's RequestRecords (0, 1 or 2)
        snapshots = self.reasoner.snapshots[self._snapshots_before:]         # bound 1:1 to requests (same count by construction)
        receipts = rec.receipts[self._receipts_before:]
        drafts = rec.draft_payloads[self._drafts_before:]
        ledger = tuple(self.store.load(self.project_id))
        state = self.governor.state(); view = derive_view(state.semantic)   # degrade ladder: view→None, then state→None, then minimal record
        measurements = measure_step(arm=self.arm, t=self.t, records=requests, receipts=receipts) if status == "COMPLETED" and len(receipts) == len(requests) else ()
        return CellRecord(
            arm=self.arm, t=self.t, position=self.position, status=status, error=error, project_id=self.project_id,
            evidence_ids_shown=tuple(sorted({e for r in requests for e in r.citable_evidence_ids})),
            requests=tuple(requests), reference_snapshots=tuple(snapshots),
            stage_decisions=outcome.stage_decisions if outcome else ((), ()),
            neighborhood=outcome.neighborhood if outcome else (),
            claim_neighborhood=getattr(outcome, "claim_neighborhood", ()) if outcome else (),   # DeltaOutcome has it; AblationOutcome does not → ()
            pending_supersede_judgment_ids=outcome.pending_supersede_judgment_ids if outcome else (),
            root_designations=tuple(root_designations), eligible_targets=eligible, authorizations=tuple(authorizations),
            measurements=measurements, receipts=tuple(receipts), draft_payloads=tuple(drafts),
            state_snapshot=state, view_snapshot=view, ledger=ledger,
        )
```

`run_reconstruction_step(*, t, position, reasoner, clock, id_factory)`: `store = InMemoryEventStore()` (straight-line, unlooped); `governor = SemanticGovernor(store=store, project_id=r_project_id(t), policy=AdmissionPolicy(), clock=clock, id_factory=id_factory)`; `capture = _StepCapture(arm="R", t=t, position=position, project_id=r_project_id(t), store=store, governor=governor, reasoner=reasoner)`; `reasoner.recording.begin_step(t)`; `outcome = assimilate_delta(governor=governor, reasoner=reasoner, delta=reconstruction_corpus(t, project_id=r_project_id(t)), scope=SCOPE)`; `return capture.record(status="COMPLETED", error=None, outcome=outcome)`; the store and governor are then dropped (no reference survives the call). `BudgetedReasoner.propose`: refuse when `budget.frontier_calls >= MAX_FRONTIER_CALLS`; increment on forward; `finally` account new receipts exactly once (`> 1` new receipt → `RuntimeError("RECEIPT_INTEGRITY…")`); after accounting, `provider_cost_usd > Decimal(str(MAX_COST_USD))` → raise `ExperimentBudgetExceeded`. `_classify`: `XAIProviderError`→ABORTED_PROVIDER, `SemanticOutputError`→ABORTED_MODEL_CONTRACT, `AuthorizationCeilingExceeded`→ABORTED_AUTHORITY_CEILING, `ExperimentBudgetExceeded`→ABORTED_BUDGET, `KeyboardInterrupt`→ABORTED_RUNTIME (`INTERRUPTED: KeyboardInterrupt`), other `Exception`→ABORTED_RUNTIME; never catch `SystemExit`.

- [ ] **Step 4: GREEN + checks + commit**

```bash
uv run pytest -q tests/unit/test_long_horizon_bounded_runner.py -p no:cacheprovider
uv run ruff check src/foundry/experiments/long_horizon_bounded/runner.py tests/unit/test_long_horizon_bounded_runner.py
uv run mypy src/foundry/experiments/long_horizon_bounded
git add src/foundry/experiments/long_horizon_bounded/runner.py tests/unit/test_long_horizon_bounded_runner.py
git commit -m "experiment: implement 9P3 three-arm runner"
```

---

## T5 — Leakage gate and integrity gates I1–I15

**Commit:** `experiment: add 9P3 leakage and integrity gates`

**Files:**
- Create: `src/foundry/experiments/long_horizon_bounded/leakage.py`, `integrity.py`
- Test: `tests/unit/test_long_horizon_bounded_leakage.py`, `tests/unit/test_long_horizon_bounded_integrity.py`

**Interfaces — produces:**

```python
# leakage.py  (may import expectations)
SKELETON_IDS: Final = ("F_T1_CALL1","F_CORRECTION_CALL1_TOUCHED","F_CORRECTION_CALL2_TOUCHED","F_RESTATEMENT_CALL1_TOUCHED","F_RESTATEMENT_CALL2_TOUCHED","A_CALL1_NO_CLAIMS","A_CALL2_WITH_CLAIMS_NO_CONTEXT","R_CUMULATIVE_CALL1","R_CUMULATIVE_CALL2")
NeedleKind = Literal["PROSE", "CANONICAL_LABEL", "CHECKPOINT_LABEL"]
class LeakageNeedle(FrozenModel): value: str; kind: NeedleKind          # spec §15.1 typed matching law
def typed_needles() -> tuple[LeakageNeedle, ...]   # the sealed inventory with its matcher kind, deterministic order (sorted by (kind, value)):
#   PROSE            = every checkpoint expected_current_meaning and requirement sentence, BASELINE_MEANINGS, CURRENT_MEANING_BY_T values, R_GRADING_RULES
#   CANONICAL_LABEL  = the five transition-class labels, DECISION_NAMES, "I1".."I15", "errors_F", "errors_A", "errors_R"
#   CHECKPOINT_LABEL = "C02".."C16"
def needles() -> tuple[str, ...]                  # complete deterministic value inventory = tuple(n.value for n in typed_needles()); kept for artifact compatibility; membership unchanged
def needle_set_sha256() -> str                    # spec §15.1 recipe: entries f"{kind}\x00{value}" over UNNORMALIZED values, sorted by code point, joined with "\x1e", sha256 of UTF-8
def matches(needle: LeakageNeedle, haystack: str) -> bool
#   PROSE:            normalize_leakage_text(needle.value) in normalize_leakage_text(haystack)           (C1; unchanged)
#   CANONICAL_LABEL:  re.search(rf"(?<![A-Za-z0-9_-]){re.escape(needle.value)}(?![A-Za-z0-9_-])", haystack)   — case-SENSITIVE, raw haystack
#   CHECKPOINT_LABEL: re.search(rf"(?<![A-Za-z0-9_-]){re.escape(needle.value)}(?![A-Za-z0-9_-])", haystack)   — case-SENSITIVE, raw haystack
class SkeletonRecord(FrozenModel): skeleton_id; sha256; chars
class LeakageResult(FrozenModel): passed; needle_set_sha256; skeletons; fr_prompt_sha256; a_prompt_sha256; matched_needle: str | None; matched_needle_kind: NeedleKind | None; matched_skeleton_id: str | None
def build_skeletons() -> dict[str, str]     # real governor + real assembly/ablation + real render_request; opaque stand-in evidence content "<EVIDENCE:EV-O-A01>" with real ids/refs/lineage; evidence content substituted out before scanning
def run_leakage_gate(*, extra_harness_text: tuple[str, ...] = ()) -> LeakageResult
REQUEST_PATH_MODULES: Final = ("timeline.py","protocol.py","designation.py","authority.py","measurements.py","runner.py")
def request_path_import_gate(sources: Mapping[str, str]) -> tuple[bool, str]   # rejects foundry.experiments.long_horizon_bounded.expectations, .expectations, from-package import expectations, named grading helpers; all six keys required

# integrity.py
GATE_NAMES: Final = ("head_equals_final_seal","worktree_clean","seal_descends_from_frozen_core","core_paths_unchanged_since_frozen_core","fr_policy_is_9p2","fr_prompt_hash_frozen","a_policy_is_9p","a_prompt_hash_frozen","output_schema_hash_frozen","f_calls_per_delta_is_2","a_two_calls_no_retry","r_uses_fresh_ledger_per_t","evidence_manifest_frozen","arm_schedule_frozen","ceilings_frozen","answer_key_not_imported_by_request_path","leakage_gate_passes","track_a_regression_passes","scope_closure_regression_passes","historical_artifacts_unchanged","grpc_dns_resolver_is_native","predecessor_raw_evidence_unchanged","r_cumulative_context_within_bounds")
HISTORICAL_PRESERVATION_BASE_SHA: Final = "43e5ea60cd92b700db4c58314a5ce68c50028169"   # approved 9P3 design commit; every dir below exists there as accepted evidence
HISTORICAL_ARTIFACT_DIRS: Final[tuple[str, ...]] = (
    "docs/superpowers/experiments/2026-09-11-incremental-semantic-assimilation-longitudinal/",
    "docs/superpowers/experiments/2026-09-11-intent-v2-foundry-self-dogfood/",
    "docs/superpowers/experiments/2026-09-12-incremental-semantic-assimilation-longitudinal-v2/",
    "docs/superpowers/experiments/2026-09-12-contrastive-unseen-lifecycle-v1/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v2/",
    "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/",
)
PREDECESSOR_RAW_EVIDENCE_SHA: Final = "201198f60c51e16269451e7d582027361d7e8a24"
PREDECESSOR_ARTIFACT_DIR: Final = "docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/"
GATE_I13_NAME: Final = "r_cumulative_context_within_bounds"
GATE_I14_NAME: Final = "leakage_gate_passes"
def preflight(*, git: GitCliLike, commands: CommandRunnerLike, frozen_sha, manifest: Mapping, expectations_bytes: bytes, request_path_sources: Mapping[str,str], leakage: LeakageResult, observed_grpc_dns_resolver: str | None) -> tuple[GateResult, ...]
# post-run deterministic verdicts over a RunResult (I1–I15 per spec §12):
class IntegrityVerdict(FrozenModel): id: str; passed: bool | None; detail: str; applies_to: tuple[Arm, ...]
class PreflightGateMissing(RuntimeError)
def integrity_verdicts(run: RunResult, *, preflight_gates: tuple[GateResult, ...]) -> tuple[IntegrityVerdict, ...]
#   I13 consumes exactly the gate named GATE_I13_NAME; I14 exactly GATE_I14_NAME. Fail closed (raise PreflightGateMissing) if either
#   name is absent from preflight_gates or appears more than once; the verdict is PASS iff that gate's passed is True.
class CallJudgments(NamedTuple):
    record: RequestRecord; snapshot: RequestReferenceSnapshot; judgments: tuple[SemanticJudgment, ...]   # judgments = the model-originated judgments the governor recorded for this call, in submission order
def request_only_reference_check(calls: tuple[CallJudgments, ...]) -> tuple[bool, str]   # I10
def r_context_within_bounds() -> tuple[bool, str]   # I13 ⊙: compile R Call-1 requests for T1..T16 via the real assembly path; T16 canonical context <= 100_000 chars
```

**Typed leakage matching law (spec §15.1; architect amendment before sealing).** Every needle carries exactly one `NeedleKind` and is matched by that kind's matcher only:
- `PROSE` (answer-key sentences: checkpoint expected meanings and requirement sentences, baseline/current hidden meanings, R grading rules) — the exact 9P2 C1 normalization: `normalize_leakage_text` (casefold + ASCII-whitespace collapse) applied to both needle and haystack, then substring containment.
- `CANONICAL_LABEL` (the five transition-class labels `RESTATEMENT`, `CORRECTION`, `REVERT`, `COMPATIBLE_EXTENSION`, `SEMANTIC_NO_OP`; `DECISION_NAMES`; `I1`..`I15`; `errors_F`/`errors_A`/`errors_R`) — exact, case-SENSITIVE, standalone identifier token on the raw (un-casefolded) haystack, boundary `(?<![A-Za-z0-9_-])…(?![A-Za-z0-9_-])`. Never casefolded; never removed from the needle set. The English words `restatement` / `correction` in the frozen prompts are therefore not matches; the canonical tokens `RESTATEMENT` / `CORRECTION` are.
- `CHECKPOINT_LABEL` (`C02`..`C16`) — case-SENSITIVE standalone identifier token with identifier characters `[A-Za-z0-9_-]`, i.e. `(?<![A-Za-z0-9_-])C02(?![A-Za-z0-9_-])`. `EV-O-C02` (frozen evidence id) and `prefix-C02` / `C02_suffix` are not standalone and do not match; `checkpoint C02 failed` does.
- Haystack: each skeleton after evidence-CONTENT substitution only. Evidence ids, lineage refs, scope and every other structural token stay in the haystack; there is NO evidence-id substitution.
- `needle_set_sha256()`: one recipe — for every typed needle the entry `f"{kind}\x00{value}"` over the UNNORMALIZED value; entries sorted by code point; joined with `"\x1e"`; SHA-256 of the UTF-8 bytes, hex. Same value under a different kind → different hash.
- `needles()` stays `tuple[str, ...]` and is the complete value inventory (`tuple(n.value for n in typed_needles())`); the kind lives in the adjacent `typed_needles()` mapping. Membership is unchanged from the enumerated §15 set.

**Scientific effect of this amendment:** only the matching semantics of the leakage gate change (how a needle is compared to a skeleton). No hypothesis, arm, model, policy, prompt, prompt hash, schema hash, corpus, corpus hash, evidence id, answer key, transition class, authority rule, measurement, threshold, precedence rule or expected result changes. It is made before sealing and before any live call; the sealed manifest records the typed `needle_set_sha256`.

- [ ] **Step 1: Leakage tests (RED)** — `needles()` contains every checkpoint id, class label, decision name, expected meaning and requirement sentence, and no Orion section text; `typed_needles()` assigns exactly one kind per value (`C02`..`C16` → `CHECKPOINT_LABEL`; class labels, decision names, `I1`..`I15`, `errors_*` → `CANONICAL_LABEL`; every sentence → `PROSE`) and `needles() == tuple(n.value for n in typed_needles())`; all nine skeletons render (F/R five-key with `CONTRASTIVE_SYSTEM_INSTRUCTION`, A four-key with `SYSTEM_INSTRUCTION`); the default gate PASSES on the frozen prompts and real skeletons with evidence ids present in the haystack; `request_path_import_gate` on the six real files PASSES, on a synthetic source importing `.expectations` in each of the 12 forms FAILS, on a mapping missing `runner.py` FAILS. Numbered typed-matching regressions (each RED before `leakage.py` exists, GREEN after; the injected text goes through `extra_harness_text`, i.e. structural harness text, never through evidence content):
  1. prompt collision — `extra_harness_text=("CORRECTION",)` → FAILS, `matched_needle == "CORRECTION"`, `matched_needle_kind == "CANONICAL_LABEL"`;
  2. prompt collision — `("a correction of a known claim is exactly",)` (the frozen-prompt wording) → PASSES;
  3. prompt collision — `("RESTATEMENT",)` → FAILS with kind `CANONICAL_LABEL`;
  4. prompt collision — `("never emit a duplicate assert_claim for a restatement.",)` → PASSES; and the unmodified default gate PASSES although both frozen prompts contain `restatement`/`correction` (asserted in the test by reading the two frozen instruction constants);
  5. checkpoint collision — `("C02",)` → FAILS, `matched_needle == "C02"`, kind `CHECKPOINT_LABEL`;
  6. checkpoint collision — `("checkpoint C02 failed",)` → FAILS on `C02`;
  7. checkpoint collision — `("EV-O-C02",)` → PASSES, and the real `R_CUMULATIVE_*` skeletons (which carry `EV-O-C02`..`EV-O-C<TT>`) PASS;
  8. checkpoint collision — `("prefix-C02", "C02_suffix", "c02")` → PASSES (not standalone / wrong case);
  9. prose — one checkpoint `expected_current_meaning` injected with different casing and doubled ASCII whitespace → FAILS with kind `PROSE` (C1 normalization retained);
  10. prose — the same sentence placed only inside stand-in evidence content of a skeleton → PASSES (evidence-content substitution unchanged), while the same sentence in `extra_harness_text` FAILS;
  11. hash — `needle_set_sha256()` equals a test-side recomputation of the documented recipe (`f"{kind}\x00{value}"`, sorted, `"\x1e"`-joined, SHA-256 UTF-8) over `typed_needles()`;
  12. hash — recomputing with one value's kind changed (e.g. `C02` as `PROSE`) yields a different digest; recomputing over normalized values yields a different digest (the hash commits to unnormalized values);
  13. hash — `needle_set_sha256()` is deterministic across two calls and independent of `typed_needles()` construction order;
  14. skeleton law — each of the nine skeletons contains the real evidence ids and lineage refs and NO Orion section text and NO `<EVIDENCE:` content other than the opaque descriptors; the `LeakageResult.skeletons` sha/chars equal the rendered skeletons;
  15. skeleton law — the gate fails closed on the FIRST match (single `matched_needle`/`matched_skeleton_id`, `passed is False`) and `LeakageResult` is `passed=True` with `matched_needle is None and matched_needle_kind is None and matched_skeleton_id is None` on the default run.

- [ ] **Step 2: Integrity tests (RED)** — fake `GitCliLike`/`CommandRunnerLike`, a manifest fixture built from T1/T5 values; every gate PASSES on correct input and FAILS on one corruption (dirty tree; changed core path; wrong prompt hash; missing runner source; non-zero pytest exit; resolver `None`/`""`/`"ares"`/`"Native"`; for `historical_artifacts_unchanged`: a FakeGit whose `tree_sha(HISTORICAL_PRESERVATION_BASE_SHA, dir)` differs from `tree_sha(frozen_sha, dir)` for any one of the six frozen dirs, a manifest whose `historical_artifact_tree_hashes[dir]` differs from the baseline tree, a manifest missing one of the six dirs, and `HISTORICAL_PRESERVATION_BASE_SHA` not an ancestor; for `predecessor_raw_evidence_unchanged`: a changed path under `PREDECESSOR_ARTIFACT_DIR` between `201198f` and the seal, and `PREDECESSOR_RAW_EVIDENCE_SHA` not an ancestor; R T16 context over 100,000 by monkeypatching the bound). `integrity_verdicts(run, preflight_gates=gates)` where `gates` is the tuple returned by the passing `preflight` call of the same test: with the full passing gate tuple I13/I14 are PASS; with the I13 or I14 gate absent → `PreflightGateMissing`; with the gate present twice → `PreflightGateMissing`; with the gate present but failed → the verdict is FAIL. Post-run: build a scripted `RunResult` (T4 fakes) and prove each I1–I15 verdict PASSES on it and FAILS under one mutation each — I1 duplicate root address; I2 a cell with one request; I3 a duplicate request sha (retry shape); I4 a proposal citing a non-request evidence id; I5 a cited predecessor present only in comparison context; I6 an out-of-scope known address; I7 a model SUPERSEDE routed APPLY; I8 an applied AGREE with no matching pending signature; I9 replay mismatch; **I10** — build `CallJudgments` from a real `RequestRecord` + `RequestReferenceSnapshot` pair and prove: a SUPERSEDE whose `target_judgment_id` is the creating judgment of a claim asserted by a sibling draft in the same response (an id absent from `known_claim_creating_judgment_ids`) FAILS; an ASSERT at an address not in `known_address_ids` FAILS; a SUPPORTS of a claim not in `known_claim_ids` FAILS; a proposal citing evidence not in `citable_evidence_ids` FAILS; the legitimate correction shape — ASSERT at a known address plus SUPERSEDE of a known claim's `created_by_judgment_id` taken from the snapshot — PASSES; a snapshot whose `request_sha256`/`arm`/`t`/`call_number` differ from its `RequestRecord` raises `ReferenceSnapshotMismatch` (evaluated as FAIL); a snapshot whose `known_claim_ids` are the same set in a different order raises `ReferenceSnapshotMismatch`; a snapshot whose creating-judgment tuple length differs raises `ReferenceSnapshotMismatch`; I11 a superseded judgment missing from the final ledger; I12 receipts/requests count mismatch; I15 an AGREE whose target is outside that T's `EligibleTargets.eligible_judgment_ids`, an AGREE at a non-checkpoint T, and an authority record carrying rationale text beyond `AGREE: <id>`.

- [ ] **Step 3: Run RED** → `ImportError` on both modules.

- [ ] **Step 4: Implement `leakage.py`** — `NeedleKind`/`LeakageNeedle`/`typed_needles()`/`needles()`/`matches()` per the typed law above; `normalize_leakage_text` imported from `contrastive_unseen.leakage` and applied ONLY to `PROSE` needles; `CANONICAL_LABEL` and `CHECKPOINT_LABEL` matched case-sensitively as standalone identifier tokens (`(?<![A-Za-z0-9_-])` … `(?![A-Za-z0-9_-])`, `re.escape` on the value) against the raw haystack; `needle_set_sha256()` implements the documented `kind\x00value` / `\x1e` recipe over unnormalized values; skeleton governor with opaque descriptors; scanning after evidence-content substitution only (no evidence-id substitution); fail closed on first match, reporting `matched_needle`, `matched_needle_kind`, `matched_skeleton_id`. No other matcher, no fuzzy/lexical logic beyond these three.

- [ ] **Step 5: Implement `integrity.py`** — gates per spec §12/§15 carried forward from 9P2 (gate 1 = full seal rule: HEAD == frozen sha, single parent == `manifest["harness_code_sha"]`, parent..HEAD names exactly the two prereg files); gate `predecessor_raw_evidence_unchanged`: `git.is_ancestor(PREDECESSOR_RAW_EVIDENCE_SHA, frozen_sha)` and no changed path under `docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/` since it, and manifest `predecessor_raw_evidence_sha` equals the literal; `historical_artifacts_unchanged` requires `git.is_ancestor(HISTORICAL_PRESERVATION_BASE_SHA, frozen_sha)` and, for every dir in `HISTORICAL_ARTIFACT_DIRS`, `git.tree_sha(HISTORICAL_PRESERVATION_BASE_SHA, dir) == git.tree_sha(frozen_sha, dir) == manifest["historical_artifact_tree_hashes"][dir]` (the `GitCliLike` protocol for 9P3 adds `tree_sha(sha: str, path: str) -> str`, implemented by the CLI as `git rev-parse <sha>:<path>`; the baseline is never computed from the mutable harness HEAD); `r_cumulative_context_within_bounds` builds a fresh `SemanticGovernor` per T, ingests `reconstruction_corpus(t, project_id=r_project_id(t))`, calls `assemble_assimilation_request(project_id=r_project_id(t), delta=<that corpus>, state=governor.state(), scope=SCOPE)` for t in 1..16 with no reasoner, and reports every `comparison_context_character_count`, failing if any raises `ContextUnsupported` or if T16 exceeds 100,000. I10 implementation over the reused `RequestRecord` and the T4 `RequestReferenceSnapshot`:

```python
class _References(NamedTuple):
    evidence: frozenset[str]; addresses: frozenset[str]; claims: frozenset[str]; targets: frozenset[str]

def _references(judgment: SemanticJudgment) -> _References:
    """Structural read of every id a proposal refers to (no wording)."""
    p = judgment.proposal
    evidence = set(judgment.visible_evidence_ids); addresses: set[str] = set(); claims: set[str] = set(); targets: set[str] = set()
    match p:
        case CreateAddressProposal():      evidence |= set(p.candidate.evidence_ids)
        case BindToAddressProposal():      evidence |= set(p.candidate.evidence_ids); addresses.add(p.address_id)
        case AssertClaimProposal():        evidence |= set(p.evidence_ids); addresses.add(p.address_id)
        case SupportsClaimProposal():      evidence |= set(p.evidence_ids); claims.add(p.claim_id)
        case SupersedeProposal():          targets.add(p.target_judgment_id)
        case ConflictsWithProposal():      claims |= set(p.claim_ids)          # frozenset pair field per the frozen adapter contract
        case EquivalentProposal() | DistinctProposal():  addresses |= set(p.address_ids)
    return _References(frozenset(evidence), frozenset(addresses), frozenset(claims), frozenset(targets))

def _bound(record: RequestRecord, snapshot: RequestReferenceSnapshot) -> None:
    """The snapshot must agree with its RequestRecord exactly (same call identity and same tuples, same order) before
    known_claim_creating_judgment_ids may be used."""
    if (record.arm, record.t, record.call_number, record.request_sha256) != (snapshot.arm, snapshot.t, snapshot.call_number, snapshot.request_sha256):
        raise ReferenceSnapshotMismatch(f"snapshot identity differs from RequestRecord at {record.arm} T{record.t} call {record.call_number}")
    if (record.citable_evidence_ids, record.known_address_ids, record.known_claim_ids) != (snapshot.citable_evidence_ids, snapshot.known_address_ids, snapshot.known_claim_ids):
        raise ReferenceSnapshotMismatch(f"snapshot reference tuples differ from RequestRecord at {record.arm} T{record.t} call {record.call_number}")
    if len(snapshot.known_claim_creating_judgment_ids) != len(snapshot.known_claim_ids):
        raise ReferenceSnapshotMismatch("creating-judgment tuple length differs from known-claim tuple length")

def request_only_reference_check(calls: tuple[CallJudgments, ...]) -> tuple[bool, str]:
    for call in calls:
        _bound(call.record, call.snapshot)                                   # raises → the gate is evaluated as FAIL by the caller
        evidence = frozenset(call.snapshot.citable_evidence_ids)
        addresses = frozenset(call.snapshot.known_address_ids)
        claims = frozenset(call.snapshot.known_claim_ids)
        creating = frozenset(call.snapshot.known_claim_creating_judgment_ids)
        for judgment in call.judgments:
            refs = _references(judgment)
            if not (refs.evidence <= evidence and refs.addresses <= addresses and refs.claims <= claims and refs.targets <= creating):
                return False, (f"request-only reference law violated by {judgment.judgment_id} at "
                               f"{call.record.arm} T{call.record.t} call {call.record.call_number}")
    return True, "every reference resolves against its exact request; no same-response id used"
```

`integrity_verdicts` builds `calls` per arm by pairing, in order, each `CellRecord.requests[i]` with `CellRecord.reference_snapshots[i]` and the model-originated judgments recorded in that cell's ledger between the two admission batches (`stage_decisions[0]` → call 1 judgments, `stage_decisions[1]` → call 2 judgments, resolved by judgment id). Because the snapshot's four tuples are copied from the request object before it is forwarded, an id minted while wrapping a sibling draft of the same provider response can never appear in any of them. I15: for each applied human SUPERSEDE, find the `EligibleTargets` of that (arm, t), require target ∈ `eligible_judgment_ids`, a pending model proposal with equal signature earlier in the ledger, route APPLY + `HUMAN_AUTHORITY`, `t in AUTHORITY_CHECKPOINTS`, rationale exactly `AGREE: <pending id>`.

- [ ] **Step 6: GREEN + checks + commit**

```bash
uv run pytest -q tests/unit/test_long_horizon_bounded_leakage.py tests/unit/test_long_horizon_bounded_integrity.py -p no:cacheprovider
uv run ruff check src/foundry/experiments/long_horizon_bounded tests/unit/test_long_horizon_bounded_leakage.py tests/unit/test_long_horizon_bounded_integrity.py
uv run mypy src/foundry/experiments/long_horizon_bounded
git add src/foundry/experiments/long_horizon_bounded/leakage.py src/foundry/experiments/long_horizon_bounded/integrity.py tests/unit/test_long_horizon_bounded_leakage.py tests/unit/test_long_horizon_bounded_integrity.py
git commit -m "experiment: add 9P3 leakage and integrity gates"
```

---

## T6 — Sealed artifacts and post-freeze adjudication

**Commit:** `experiment: add 9P3 sealed artifacts`

**Files:**
- Create: `src/foundry/experiments/long_horizon_bounded/artifacts.py`
- Test: `tests/unit/test_long_horizon_bounded_artifacts.py`

**Interfaces — produces:**

```python
ARTIFACT_FORMAT_VERSION = 1
SPEC_PATH = "docs/superpowers/specs/2026-09-13-9p3-long-horizon-bounded-memory-design.md"
EXPERIMENT_ARTIFACT_DIR = "docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/"
FINAL_SEAL_RULE = "live HEAD must equal --frozen-sha; its single parent must equal harness_code_sha; parent..HEAD may add only manifest.json and expectations.json"
class ExperimentManifest(FrozenModel):   # keys read by integrity gates use the same names
    experiment_version; artifact_format_version; frozen_core_sha; predecessor_raw_evidence_sha; harness_code_sha; final_seal_rule; spec_path; spec_sha256
    provider; model; reasoning_effort; grpc_dns_resolver; fr_policy_version; fr_prompt_sha256; a_policy_version; a_prompt_sha256; output_schema_sha256
    arm_schedule: tuple[tuple[int, str], ...]; ceilings: Ceilings (six fields); evidence: tuple[EvidenceRecord, ...]; corpus_sha256
    leakage_needle_set_sha256; expectations_sha256
    economy_rule = "4*X_TOTAL <= 3*R_TOTAL for X in {F, A}, T2..T16 input tokens"; bounded_growth_rule = "X_LATE_MEAN <= 27/20 * X_EARLY_MEAN"; r_growth_rule = "R_LATE_MEAN >= 3/2 * R_EARLY_MEAN"; token_diff_rule = "abs(F_TOTAL-A_TOTAL)/min(F_TOTAL,A_TOTAL) >= 1/20 is meaningful"
    early_window; late_window; decision_names
    historical_preservation_base_sha: str = HISTORICAL_PRESERVATION_BASE_SHA      # frozen literal, never the harness HEAD
    historical_artifact_dirs: tuple[str, ...] = HISTORICAL_ARTIFACT_DIRS         # the six frozen dirs, in that order
    historical_artifact_tree_hashes: dict[str, str]   # dir -> git tree sha of that dir AT historical_preservation_base_sha (git rev-parse <BASE>:<dir>)
    predecessor_artifact_dir: str = PREDECESSOR_ARTIFACT_DIR; lifecycle_project_id; scope
def build_manifest(*, harness_code_sha: str, spec_sha256: str, historical_tree_hashes: Mapping[str, str]) -> ExperimentManifest
#   build_manifest requires historical_tree_hashes to have exactly the six frozen dirs as keys (40-hex values), else ValueError.
def write_preregistration(out_dir: Path, manifest) -> dict[str, str]
def existing_raw_artifacts(out_dir: Path) -> tuple[str, ...]
RAW_ARTIFACT_PATHS: Final[tuple[str, ...]] = (
    "preflight.json", "measurements.json", "verdicts.json", "report.md",
    *(f"{arm}/{name}.json" for arm in ("F", "A") for name in ("requests", "drafts", "receipts", "decisions", "eligible_targets", "authorizations", "ledger", "result")),
    *(f"R/T{t:02d}/{name}.json" for t in range(1, 17) for name in ("requests", "drafts", "receipts", "decisions", "ledger", "result")),
)   # 4 + 16 + 96 = 116 paths; every requests.json entry is {"record": RequestRecord dump, "reference_snapshot": RequestReferenceSnapshot dump}
    # bound by (arm, t, call_number, request_sha256); measurements.json rows serialize r_cumulative_raw_evidence_chars as null for F/A
def write_preflight(out_dir, gates, *, frozen_sha, leakage, observed_grpc_dns_resolver) -> Path
def write_run_artifacts(out_dir, run: RunResult, verdicts: tuple[IntegrityVerdict, ...]) -> tuple[str, ...]   # write-once; secret scan; NOT_RUN cells written
def write_adjudication(out_dir, *, raw_run_commit_sha: str, git: GitCliLike, adjudication: Adjudication) -> tuple[str, ...]
class Adjudication(FrozenModel): checkpoints: dict[Arm, dict[str, bool]] (C02..C16); control_errors: dict[Arm, int]; material_errors: dict[Arm, int]; notes: str
```

- [ ] **Step 1: Tests (RED)** — manifest canonical hash stable across mapping insertion order; `expectations_sha256 == canonical_sha256(expectations_document())`; `corpus_sha256 == timeline.corpus_sha256()`; `historical_preservation_base_sha == "43e5ea60cd92b700db4c58314a5ce68c50028169"` and `historical_artifact_dirs == HISTORICAL_ARTIFACT_DIRS` (the six frozen dirs), and `build_manifest` raises `ValueError` when `historical_tree_hashes` lacks a dir, has an extra dir, or a non-40-hex value; every `requests.json` entry pairs a record with its snapshot and the pair agrees on `(arm, t, call_number, request_sha256)`; `measurements.json` F/A rows carry `null` for `r_cumulative_raw_evidence_chars` and R rows carry the integer; `write_preregistration` writes exactly two files and refuses if either exists; raw tree from a scripted COMPLETED run equals `RAW_ARTIFACT_PATHS` exactly (48 cells: F/A folders aggregate 16 steps each, R/T01..T16); an aborted run still writes every cell with NOT_RUN results and `measurements.json`; overwrite refusal is all-or-nothing (a stray `R/T09/ledger.json` leaves the tree unchanged); requests preserve exact rendered text and sha; a secret-shaped `rendered_user_request` refuses the whole write, secret-shaped error text is redacted; `verdicts.json` after COMPLETED carries I1–I15 deterministic verdicts (I2 through I15 where computable) and `semantic_checkpoints`, `material_errors`, `control_errors`, `errors_total`, `architecture_selection` all `null`; `report.md` contains `architecture_selection = null (architect adjudication pending)`; `write_adjudication` refuses when `git.head() != raw_run_commit_sha` or the working tree is dirty or the raw files' hashes differ from those at `raw_run_commit_sha` (`git.show_bytes`), and on success writes only `verdicts.json` and `report.md` (all other raw files byte-identical before/after) and computes `select_architecture` from the adjudication plus `measurements.json`; no path under any historical experiment dir is touched (snapshot before/after).

- [ ] **Step 2: Run RED** → `ImportError`.

- [ ] **Step 3: Implement** — `canonical_bytes`/`canonical_sha256`/`pretty_json` imported from `contrastive_unseen.artifacts`; `redact_secrets`/`contains_secret_shape` from `longitudinal.artifacts`; manifest built only from frozen constants, `evidence_records()`, `needle_set_sha256()`, `expectations_document()`; the live runner path never calls `select_architecture` (only `write_adjudication` does).

- [ ] **Step 4: GREEN + checks + commit**

```bash
uv run pytest -q tests/unit/test_long_horizon_bounded_artifacts.py -p no:cacheprovider
uv run ruff check src/foundry/experiments/long_horizon_bounded/artifacts.py tests/unit/test_long_horizon_bounded_artifacts.py
uv run mypy src/foundry/experiments/long_horizon_bounded
git add src/foundry/experiments/long_horizon_bounded/artifacts.py tests/unit/test_long_horizon_bounded_artifacts.py
git commit -m "experiment: add 9P3 sealed artifacts"
```

---

## T7 — Prepare and run entry points

**Commit:** `experiment: add 9P3 entrypoints`

**Files:**
- Create: `scripts/prepare_long_horizon_bounded_memory.py`, `scripts/run_long_horizon_bounded_memory.py`
- Test: `tests/integration/test_long_horizon_bounded_entrypoint.py`

**Prepare script** (`main(argv, *, cwd) -> int`): `--out` default `docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1`; git via `subprocess` only for `status --porcelain` (must be empty), `rev-parse HEAD` (= `harness_code_sha`), `merge-base --is-ancestor <FROZEN_CORE_SHA> HEAD`, `merge-base --is-ancestor <PREDECESSOR_RAW_EVIDENCE_SHA> HEAD`, `merge-base --is-ancestor <HISTORICAL_PRESERVATION_BASE_SHA> HEAD`, `show HEAD:<SPEC_PATH>` (must equal working-tree bytes), and for every dir in `HISTORICAL_ARTIFACT_DIRS` both `rev-parse <HISTORICAL_PRESERVATION_BASE_SHA>:<dir>` (the baseline tree sha recorded in the manifest) and `rev-parse HEAD:<dir>` (must equal the baseline, else refuse — the baseline is never taken from HEAD); refuses if either prereg file exists; writes exactly the two files; prints canonical hashes; no key, no reasoner, no network.

**Run script** (`main(argv, *, cwd, env, reasoner_factory, git, commands) -> int`): mutually exclusive `--preflight-only` | `--live`; `--frozen-sha` (40 lowercase hex) and `--out` required; `observed_grpc_dns_resolver = env.get("GRPC_DNS_RESOLVER")` read once before any gate in both modes; `--preflight-only` evaluates all gates (23 names of T5) with the six real request-path sources, prints the preflight document, writes nothing, never reads `XAI_API_KEY`, never calls the factory, exit 0/3; `--live`: seal files required → no existing raw artifact → all gates → `write_preflight` once → exit 3 on failure with zero calls → only then `env.get("XAI_API_KEY")` (missing → `ABORTED_RUNTIME`/`MISSING_API_KEY` tree, exit 4) → factory `default_reasoner_factory(*, api_key: str) -> tuple[SemanticReasoner, SemanticReasoner, SemanticReasoner]` returning (F `XAIContrastiveSemanticReasoner(api_key=api_key, model=MODEL, reasoning_effort=REASONING_EFFORT)`, A `XAISemanticReasoner(api_key=api_key, model=MODEL, reasoning_effort=REASONING_EFFORT)`, R `XAIContrastiveSemanticReasoner(api_key=api_key, model=MODEL, reasoning_effort=REASONING_EFFORT)`) → `build_arm_reasoners` → identity-guard wrapper (checks adapter class attributes and fingerprints against the manifest before every forwarded call; `IdentityDrift(RuntimeError)`) → `run_experiment` inside the abort-recording `try` (construction included) → `integrity_verdicts(run, preflight_gates=<the exact GateResult tuple evaluated immediately before the live run, the same object written to preflight.json>)` → `write_run_artifacts` always → exit 0 if COMPLETED else 4. Exit 2 for refusals. Never retry.

- [ ] **Step 1: Tests (RED)** — fakes only (FakeGit with realistic parent/ancestor/changed-path tables incl. the predecessor sha and the preservation base sha, plus a `tree_sha(sha, dir)` table that returns identical values at the base and at the seal for all six frozen dirs — with one test variant where a single dir differs at the seal and preflight fails only `historical_artifacts_unchanged`; FakeCommands exit codes; scripted reasoners via injected factory; `PoisonedEnv` answering only `GRPC_DNS_RESOLVER`; sockets blocked): failed preflight never reads the key and never calls the factory; preflight-only writes nothing, constructs nothing, prints 23 gates, `frontier_calls: 0`, `observed_grpc_dns_resolver: "native"`; resolver absent/`ares`/`Native` → exit 3 with only gate 21 failed; passed preflight + missing key → `ABORTED_RUNTIME`, zero calls, full tree; fake live success → full raw tree, 96 request records, 48 COMPLETED cells, `measurements.json` with 96 rows, `verdicts.json` semantic fields null, exit 0; scripted provider failure at position 20 → earlier cells preserved, later NOT_RUN, exit 4; second `--live` with existing `preflight.json` refuses (exit 2) before the factory; raising factory → `ABORTED_RUNTIME` recorded; identity guard: a 9p-v4-fingerprinted fake as F refused at construction, adapter-attribute drift → `IdentityDrift` before any forwarded call; manifest/expectations bytes unchanged after any run; `write_adjudication` end-to-end on the fake run tree with a FakeGit at the raw commit.

- [ ] **Step 2: Run RED** → `ModuleNotFoundError` for the scripts.

- [ ] **Step 3: Implement both scripts** following `scripts/prepare_contrastive_unseen_lifecycle.py` / `scripts/run_contrastive_unseen_lifecycle.py` shapes (real `GitCli`/`CommandRunner` classes; `_Refused`; `_aborted_runtime_result` with partial cells; `_say` through `redact_secrets`).

- [ ] **Step 4: GREEN + checks + commit**

```bash
uv run pytest -q tests/integration/test_long_horizon_bounded_entrypoint.py -p no:cacheprovider
uv run ruff check scripts/prepare_long_horizon_bounded_memory.py scripts/run_long_horizon_bounded_memory.py tests/integration/test_long_horizon_bounded_entrypoint.py
MYPYPATH=src uv run mypy scripts/prepare_long_horizon_bounded_memory.py scripts/run_long_horizon_bounded_memory.py
git add scripts/prepare_long_horizon_bounded_memory.py scripts/run_long_horizon_bounded_memory.py tests/integration/test_long_horizon_bounded_entrypoint.py
git commit -m "experiment: add 9P3 entrypoints"
```

---

## T8 — Whole-harness verification and review

No feature work; no commit unless a review finding requires a RED/GREEN fix commit.

- [ ] Run all new 9P3 tests and the reused/frozen regression suites:

```bash
uv run pytest -q -p no:cacheprovider tests/unit/test_long_horizon_bounded_*.py tests/integration/test_long_horizon_bounded_entrypoint.py
uv run pytest -q -p no:cacheprovider tests/unit/test_9p2_track_a_regression.py tests/unit/test_contrastive_context.py tests/unit/test_assimilation_context.py tests/unit/test_incremental_assimilation.py tests/unit/test_contrastive_unseen_*.py tests/integration/test_contrastive_unseen_entrypoint.py
uv run pytest -v -p no:cacheprovider          # record exact pass count and warning count
uv run ruff check src tests scripts
uv run ruff format --check src/foundry/experiments/long_horizon_bounded scripts/prepare_long_horizon_bounded_memory.py scripts/run_long_horizon_bounded_memory.py
uv run mypy src
MYPYPATH=src uv run mypy scripts/prepare_long_horizon_bounded_memory.py scripts/run_long_horizon_bounded_memory.py
git diff --check
git status --short
```

- [ ] Diff gates. Two different baselines apply: production is frozen at the 9P2 core; prior experiment code and artifacts are frozen at the approved 9P3 design commit (the 9P2 unseen v1/v2/v3 directories were legitimately added between those two commits, so they must not be diffed against the core).

```bash
# 1. Allowed change set since the approved design: only this plan, the new package, the two scripts, the new tests
git diff --name-only 43e5ea60cd92b700db4c58314a5ce68c50028169..HEAD

# 2. Production freeze (baseline: frozen 9P2 core)
git diff --name-only 1f89fc86cda463da676bf45603b86a7dcb458452..HEAD -- src/foundry/domain src/foundry/application src/foundry/ports src/foundry/adapters
# Expected: empty

# 3. Prior experiment preservation BEFORE the T9 seal (baseline: approved 9P3 design commit)
git diff --name-only 43e5ea60cd92b700db4c58314a5ce68c50028169..HEAD -- src/foundry/experiments/longitudinal src/foundry/experiments/contrastive_unseen docs/superpowers/experiments
# Expected: empty
```

- [ ] Prove identities and constants in-process (policies, prompt hashes, schema hash, `CALLS_PER_DELTA == 2`, 48-position schedule, ceilings), that `select_architecture` is referenced only from `artifacts.write_adjudication` and tests (grep), that no request-path module imports `expectations` (real gate over the six files), and that no live call occurred (no receipts anywhere; `XAI_API_KEY` unset in the shell).
- [ ] Use `superpowers:requesting-code-review` on `43e5ea60cd92b700db4c58314a5ce68c50028169..HEAD` with the reviewer checking: frozen-core law; reuse boundary (no forked ablation/recording); semantic law; leakage law; pre-T authority and I15; I10 request-only; fail-fast/no-retry; artifact truthfulness (NOT_RUN cells, null semantic verdicts, no selection in the live path); adjudication plumbing refuses mismatched raw trees. Resolve Critical/Important findings with RED/GREEN commits and re-review.
- [ ] Use `superpowers:verification-before-completion`: re-run the full block above fresh after any fix.

---

## T9 — Preregistration and seal

**Seal commit:** `experiment: seal 9P3 long-horizon bounded memory v1`

- [ ] With a clean verified T8 HEAD, run the prepare script once:

```bash
uv run python scripts/prepare_long_horizon_bounded_memory.py --out docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1
git status --short      # exactly the new directory with manifest.json and expectations.json
git diff --name-only    # empty
```

- [ ] Validate both JSON files: recompute canonical hashes; `manifest.expectations_sha256` equals the file's canonical hash; `expectations.json == expectations_document()`; `manifest.evidence == evidence_records()`; `corpus_sha256`, `leakage_needle_set_sha256` match in-process values; `harness_code_sha == git rev-parse HEAD`.
- [ ] Seal commit with exactly the two files:

```bash
git add docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/manifest.json docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/expectations.json
git commit -m "experiment: seal 9P3 long-horizon bounded memory v1"
SEAL_SHA=$(git rev-parse HEAD)
git rev-parse HEAD^                  # must equal manifest.harness_code_sha
git diff --name-only HEAD^..HEAD     # exactly the two preregistration files
```

- [ ] Offline post-seal preflight (no live calls):

```bash
GRPC_DNS_RESOLVER=native uv run python scripts/run_long_horizon_bounded_memory.py \
  --preflight-only \
  --frozen-sha "$SEAL_SHA" \
  --out docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1
git status --short   # empty
```
Expected: `all_passed: true`, all 23 gates PASS, `frontier_calls: 0`, `judge_calls: 0`, `human_authorizations: 0`, `observed_grpc_dns_resolver: "native"`, `run_status: null`, no file written, no key read, no network. Also demonstrate fail-closed offline with the resolver absent — `env -u GRPC_DNS_RESOLVER uv run python scripts/run_long_horizon_bounded_memory.py --preflight-only --frozen-sha "$SEAL_SHA" --out docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1` → exit 3, only `grpc_dns_resolver_is_native` failed, nothing written.
- [ ] Final seal preservation check — relative to the approved design commit, the only allowed difference under `docs/superpowers/experiments` is the two new preregistration files, and every pre-existing experiment directory is tree-identical:

```bash
git diff --name-only 43e5ea60cd92b700db4c58314a5ce68c50028169..HEAD -- docs/superpowers/experiments
# Expected, exactly:
#   docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/expectations.json
#   docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1/manifest.json
for d in 2026-09-11-incremental-semantic-assimilation-longitudinal 2026-09-11-intent-v2-foundry-self-dogfood 2026-09-12-incremental-semantic-assimilation-longitudinal-v2 2026-09-12-contrastive-unseen-lifecycle-v1 2026-09-13-contrastive-unseen-lifecycle-v2 2026-09-13-contrastive-unseen-lifecycle-v3; do
  test "$(git rev-parse 43e5ea60cd92b700db4c58314a5ce68c50028169:docs/superpowers/experiments/$d)" = "$(git rev-parse HEAD:docs/superpowers/experiments/$d)" && echo "preserved $d"
done
git diff --name-only 1f89fc86cda463da676bf45603b86a7dcb458452..HEAD -- src/foundry/domain src/foundry/application src/foundry/ports src/foundry/adapters   # empty
git diff --name-only 43e5ea60cd92b700db4c58314a5ce68c50028169..HEAD -- src/foundry/experiments/longitudinal src/foundry/experiments/contrastive_unseen   # empty
```

- [ ] Final code review of the seal commit (only two files, parent == `harness_code_sha`) and `superpowers:verification-before-completion` with fresh full pytest/ruff/mypy on the seal HEAD.
- [ ] STOP. Do not run `--live`. Do not push. Live execution requires a new explicit architect authorization after independent verification of the seal.

Allowed final conclusion: **`9P3 long-horizon bounded-memory harness locally verified and sealed; live experiment remains unauthorized pending architect verification.`**

---

## Plan self-review record

1. **Spec coverage:** §1–§2 laws → Global Constraints; §3–§5, §7 corpus → T1 timeline (byte-exact spec-block test); §6 classes and §10 checkpoints/controls/R rules → T1 expectations; §8 arms → T4 (F/R `assimilate_delta`, A reused ablation); §9 order/96 calls → T1 protocol + T4; §10.1 designation → T2; §11/§17 budgets → T1 protocol + T4 budget + T2 ceiling 48; §12 I1–I15 (+ preflight carry-overs, predecessor and historical preservation, I13 offline compile, I14 leakage) → T5; §13 measurements → T3; §14 economy/growth (exact rationals) → T1 expectations + T3 summary; §15 leakage → T5; §16 precedence/`TOKEN_DIFF_FA`/examples → T1 expectations (live runner never calls it; only T6 `write_adjudication`); §18 pre-T authority + I15 → T2 + T4 + T5; §19 freeze discipline → T6/T7/T9; §20 no production changes → Global Constraints 4–6 and the T8 diff gate; §21 non-goals → nothing planned beyond them; §22–§24 → T9 stop conditions.
2. **Red-flag scan:** none of the writing-plans red-flag phrases and no unspecified steps; every code step shows the code or the exact algorithm; the 38 section texts are transcribed from the spec and locked by a byte-exact test.
3. **Type consistency:** `RootDesignation`, `EligibleTargets`, `AuthorizationRecord`, `CallMeasurement`, `TokenSummary`, `CellRecord`, `ArmSummary`, `RunResult`, `LeakageResult`, `GateResult`, `IntegrityVerdict`, `ExperimentManifest`, `Adjudication`, `SelectionInputs/Outcome`, `RequestReferenceSnapshot`, `CallJudgments`, `ReferenceSnapshotMismatch`, `PreflightGateMissing` are named identically in every task that consumes them. The reused `RequestRecord`/`RecordingReasoner` are never modified: the exact-request reference closure lives in the experiment-only `RequestReferenceSnapshot`, captured by `BudgetedReasoner` from the very `ReasoningRequest` before forwarding, bound 1:1 to the `RequestRecord` the reused recorder appends, surviving provider failure, and consumed by I10 together with the record.
4. No task modifies production code, `contrastive_unseen`, `longitudinal`, or any pre-existing experiment directory; the T8 gates split the baselines — production against the frozen core `1f89fc8…`, prior experiment code and artifacts against the approved design commit `43e5ea6…` (where all six frozen directories already exist) — so both commands pass on the real history; the new v1 directory appears only at T9 and only with the two preregistration files.
4a. Historical preservation: `HISTORICAL_ARTIFACT_DIRS` is the exact six-directory tuple, `HISTORICAL_PRESERVATION_BASE_SHA = 43e5ea6…` (never the mutable harness HEAD), prepare records baseline tree hashes from that SHA and refuses if HEAD's trees differ, preflight re-checks ancestor + baseline == seal == manifest, and the 9P2 v3 predecessor is additionally protected by `PREDECESSOR_RAW_EVIDENCE_SHA = 201198f…` (ancestor + unchanged `PREDECESSOR_ARTIFACT_DIR`).
4b. `integrity_verdicts(run, *, preflight_gates)` consumes exactly `r_cumulative_context_within_bounds` (I13) and `leakage_gate_passes` (I14) and raises `PreflightGateMissing` when either is absent or duplicated; T7 passes the exact pre-run gate tuple. `r_cumulative_raw_evidence_chars` is `int | None` (`None` for F/A, never 0).
5. No live model/provider call exists in any step; `--live` is implemented but never invoked; factories are injected in every test.
6. Architecture selection is computed only by `write_adjudication` after the raw-run commit; the live runner and `write_run_artifacts` leave it null.
7. Semantic grading (C02–C16, control errors, material errors) remains architect input to `Adjudication` after the raw freeze.
8. T8/T10 and all fifteen transitions, the approved T9 idempotent-cancellation text, I10 request-only, the 48 authorization ceiling and the 96-call ceiling are locked by T1/T2/T5 tests exactly as frozen in the spec.
9. Raw evidence commit precedes semantic adjudication: `write_adjudication` requires `git.head() == raw_run_commit_sha` and byte-identical raw files.
