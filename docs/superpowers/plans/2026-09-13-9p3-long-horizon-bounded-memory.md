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
4. Do not modify any file under `src/foundry/domain/`, `src/foundry/application/`, `src/foundry/ports/`, `src/foundry/adapters/`, `src/foundry/experiments/longitudinal/`, `src/foundry/experiments/contrastive_unseen/`, or any directory under `docs/superpowers/experiments/`. Do not modify the spec or this plan during execution.
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

Generic helpers imported read-only from the frozen 9P2 package (never modified): `contrastive_unseen.leakage.normalize_leakage_text`; `contrastive_unseen.integrity.GitCliLike`, `CommandRunnerLike`, `GateResult`, `all_passed`; `contrastive_unseen.artifacts.canonical_bytes`, `canonical_sha256`, `pretty_json`; `longitudinal.artifacts.redact_secrets`, `contains_secret_shape`; `longitudinal.scoring.replay_matches`.

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

`_predicates` computes `acceptable_X = errors_X == 0 and integrity_X`, `economy_X = 4*X_total <= 3*r_total`, `bounded_X = Fraction(late) <= BOUNDED_FACTOR * Fraction(early)`, `r_grows = Fraction(r_late) >= R_GROWTH_FACTOR * Fraction(r_early)`. `expectations_document()` returns `ExpectationsDocument(...).model_dump(mode="json")` with the checkpoints, baseline and per-T meanings, R rules, F/A/R rubric text quoted from spec §10, I1–I15 titles, thresholds as Fraction strings, the precedence text of §16.2 and the decision names.

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

**Interfaces — consumes:** `timeline.LOCI`, `timeline.Locus`, `timeline.evidence_id`; `protocol.MAX_HUMAN_AUTHORIZATIONS`; frozen `foundry.domain.semantic_view.derive_view`, `authority_record_is_live`; `foundry.domain.semantic_judgment.proposal_signature`, `SupersedeProposal`, `SemanticJudgment`, `ReasonerFingerprint`, `AdmissionRoute`; `foundry.domain.semantic.AuthorityRecord`; `SemanticGovernor.submit(judgment, human_actor_id=...)`, `record_authority`.

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
    budget.human_authorizations = 47; ...one AGREE → 48
    budget.human_authorizations = 48; with pytest.raises(AuthorizationCeilingExceeded): ...; assert ledger length unchanged

def test_no_semantic_inspection_in_authority_source():  # AST: no access to .predicate/.value/.subject/.facet/.content/.rationale text of claims
def test_undesignated_locus_authorizes_nothing()
```

- [ ] **Step 3: Run RED** — `uv run pytest -q tests/unit/test_long_horizon_bounded_designation.py tests/unit/test_long_horizon_bounded_authority.py -p no:cacheprovider`. Expected: `ImportError` on the two modules.

- [ ] **Step 4: Implement `designation.py`** — same algorithm as 9P2 (`derive_view(state.semantic).effective_evidence` keyed by live claims; collect claim ids containing the seed; map to `claims[id].address_id`; reasons exactly `NO_LIVE_SEED_SUPPORTED_CLAIM` / `MULTIPLE_SEED_SUPPORTED_ADDRESSES`; `DESIGNATED` with sorted claim ids and sorted-deduplicated `created_by_judgment_id`s). `designate_t1_roots` loops `LOCI`.

- [ ] **Step 5: Implement `authority.py`**

```python
def snapshot_eligible_targets(state, *, arm, t, target_locus, designated_address_id, ledger_length):
    if designated_address_id is None:
        return EligibleTargets(..., eligible_judgment_ids=(), live_claim_ids=())
    view = derive_view(state.semantic)
    live = sorted(cid for cid in view.effective_evidence if state.semantic.claims[cid].address_id == designated_address_id)
    judgments = tuple(sorted({state.semantic.claims[cid].created_by_judgment_id for cid in live}))
    return EligibleTargets(arm=arm, t=t, target_locus=target_locus, designated_address_id=designated_address_id,
                           eligible_judgment_ids=judgments, live_claim_ids=tuple(live), snapshot_sequence=ledger_length)

def authorize_eligible_supersessions(*, governor, eligible, pending_judgment_ids, budget, clock, id_factory):
    targets = _model_supersede_targets(governor.state(), pending_judgment_ids)  # {target_judgment_id: [pending ids]} for model-originated SUPERSEDEs
    records = []
    for target in eligible.eligible_judgment_ids:
        pending = targets.get(target, [])
        if not pending: records.append(_record(..., NO_PROPOSAL)); continue
        if len(pending) > 1: records.append(_record(..., AMBIGUOUS_PROPOSALS, pending)); continue
        if budget.human_authorizations >= MAX_HUMAN_AUTHORIZATIONS: raise AuthorizationCeilingExceeded(...)
        submitted = _submit_agreement(governor, governor.state().semantic.judgments[pending[0]], clock=clock, id_factory=id_factory)  # same shape as 9P2: pre-check live authority record, identical proposal, HUMAN_FINGERPRINT, human_actor_id="human://architect", post-check APPLY + HUMAN_AUTHORITY
        budget.human_authorizations += 1
        records.append(_record(..., AGREED, pending, submitted, proposal_signature(...)))
    for target, pending in sorted(targets.items()):
        if target not in eligible.eligible_judgment_ids:
            for pid in sorted(pending): records.append(_record(..., NOT_ELIGIBLE_NOT_AUTHORIZED, (pid,)))
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
    comparison_context_chars: int; r_cumulative_raw_evidence_chars: int   # 0 for F/A
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

- [ ] **Step 1: Tests (RED)** — with fake `RequestRecord`s and fake receipts (objects with `input_tokens`, `output_tokens`, `cost_usd`, `wall_clock_ms`, `invocation_id`): `measure_step` pairs record i with receipt i (call order) and copies fields exactly; `len(records) != len(receipts)` → `MeasurementMismatch` (fail closed, no partial output); `rendered_request_chars == len(record.rendered_user_request)`; A records must have `comparison_context_chars == 0` else `MeasurementMismatch`; R rows carry `raw_evidence_character_count(t)`, F/A rows 0; `summarize` sums T2–T16 only (T1 excluded), computes `Fraction` means over `EARLY_WINDOW`/`LATE_WINDOW`, rejects a missing (arm, t) pair in the measured window; a test that `measurements.py` imports `RecordingReasoner`/`RequestRecord` from `contrastive_unseen.records` and that no module in `long_horizon_bounded` defines a class named `RecordingReasoner` or a function named `assimilate_ablation_delta` (AST scan of the package directory).

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
class BudgetedReasoner:  # wraps RecordingReasoner; refuses call 97 before forwarding; accounts each new receipt once; raises after a cost breach before returning judgments
class ArmReasoners(NamedTuple): f: BudgetedReasoner; a: BudgetedReasoner; r: BudgetedReasoner
def build_arm_reasoners(*, inner_f, inner_a, inner_r, budget) -> ArmReasoners
class CellRecord(FrozenModel):
    arm; t; position: int (0..47); status: Literal["COMPLETED","FAILED","NOT_RUN"]; error: str | None; project_id
    evidence_ids_shown; requests: tuple[RequestRecord, ...]; stage_decisions; neighborhood; claim_neighborhood; pending_supersede_judgment_ids
    root_designations: tuple[RootDesignation, ...]; eligible_targets: EligibleTargets | None; authorizations: tuple[AuthorizationRecord, ...]
    measurements: tuple[CallMeasurement, ...]; receipts; draft_payloads; state_snapshot; view_snapshot; ledger
class ArmSummary(FrozenModel): arm; project_id; roots: dict[Locus, RootDesignation]; ledger; final_state; final_view; replay: ReplayResult | None; eligible_targets: tuple[EligibleTargets, ...]; authorizations; requests
class RunResult(FrozenModel): status; error; cells: tuple[CellRecord, ...] (len 48); f: ArmSummary; a: ArmSummary; r_cells: dict[int, CellRecord]; budget: BudgetSnapshot; measurements: tuple[CallMeasurement, ...]; schedule
def run_reconstruction_step(*, t: int, reasoner: BudgetedReasoner, clock, id_factory) -> CellRecord   # constructs InMemoryEventStore() unlooped
def run_experiment(*, reasoners: ArmReasoners, clock, id_factory, progress: list[CellRecord] | None = None) -> RunResult
```

- [ ] **Step 1: Tests (RED)** — scripted reasoners (record requests; one batch per call; callable batches that inspect the real `ReasoningRequest`; raise-able batches; optional fake receipts with cost), fingerprints per arm (`intent-v2-9p2-v1` for F/R, `intent-v2-9p-v4` for A, model `grok-4.6`), sockets blocked. Prove: 48 COMPLETED cells and 96 requests on a scripted success; positions follow `ARM_SCHEDULE` exactly; F and A ledgers persist across T (T2 request shows T1-created addresses) while every R cell has a fresh store (`store.load` sequence starts at 1; project id `PROJ-9P3-R-T{t:02d}`; no prior claims visible); no cross-arm state (A's addresses never appear in F's requests); F/R Call 1 shows `known_claims` (production path) and A Call 1 shows none (ablation path); after F/A T1 all twelve roots are designated; at every checkpoint T the `eligible_targets` snapshot's `snapshot_sequence` equals the ledger length before ingestion and authority runs only after Call 2; no `eligible_targets`/authorizations at non-checkpoint T or for R; 97th call refused before forwarding; a receipt pushing cost past `Decimal("10.0")` is recorded and no later call happens (`ABORTED_BUDGET`); status classification per exception; first failure marks later cells NOT_RUN with no further calls; summarisation failure after the walk still returns a `RunResult` with all cells (`ABORTED_RUNTIME`, `replay=None`); replay equality for F and A on success; `runner.py` imports none of `expectations`, `leakage`, `integrity`, `artifacts` (AST) and defines no ablation/recording classes.

- [ ] **Step 2: Run RED** — `uv run pytest -q tests/unit/test_long_horizon_bounded_runner.py -p no:cacheprovider` → `ImportError`.

- [ ] **Step 3: Implement** — adapt `contrastive_unseen/runner.py` structure (one `try` site `_attempt`, `_StepCapture`, degrade ladder) to 48 positions. Persistent step:

```python
def _run_persistent_step(session, t, *, clock, id_factory, budget) -> CellRecord:
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
    authorizations = ()
    if eligible is not None:
        authorizations = authorize_eligible_supersessions(governor=session.governor, eligible=eligible, pending_judgment_ids=outcome.pending_supersede_judgment_ids, budget=budget, clock=clock, id_factory=id_factory)
    ...  # capture requests/receipts/drafts/measurements/state/view/ledger into CellRecord
```

`run_reconstruction_step` constructs `store = InMemoryEventStore()` in straight-line code, a governor with `r_project_id(t)`, calls `assimilate_delta(... delta=reconstruction_corpus(t, project_id=...), scope=SCOPE)`, records, discards. `BudgetedReasoner.propose`: refuse when `budget.frontier_calls >= MAX_FRONTIER_CALLS`; increment on forward; `finally` account new receipts exactly once (`> 1` new receipt → `RuntimeError("RECEIPT_INTEGRITY…")`); after accounting, `provider_cost_usd > Decimal(str(MAX_COST_USD))` → raise `ExperimentBudgetExceeded`. `_classify`: `XAIProviderError`→ABORTED_PROVIDER, `SemanticOutputError`→ABORTED_MODEL_CONTRACT, `AuthorizationCeilingExceeded`→ABORTED_AUTHORITY_CEILING, `ExperimentBudgetExceeded`→ABORTED_BUDGET, `KeyboardInterrupt`→ABORTED_RUNTIME (`INTERRUPTED: KeyboardInterrupt`), other `Exception`→ABORTED_RUNTIME; never catch `SystemExit`.

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
def needles() -> tuple[str, ...]   # GRADING_LABELS (word-bounded), DECISION_NAMES, transition-class names, every checkpoint expected_current_meaning and requirement sentence, BASELINE/CURRENT meanings
def needle_set_sha256() -> str
class SkeletonRecord(FrozenModel): skeleton_id; sha256; chars
class LeakageResult(FrozenModel): passed; needle_set_sha256; skeletons; fr_prompt_sha256; a_prompt_sha256; matched_needle; matched_skeleton_id
def build_skeletons() -> dict[str, str]     # real governor + real assembly/ablation + real render_request; opaque stand-in evidence content "<EVIDENCE:EV-O-A01>" with real ids/refs/lineage; evidence content substituted out before scanning
def run_leakage_gate(*, extra_harness_text: tuple[str, ...] = ()) -> LeakageResult
REQUEST_PATH_MODULES: Final = ("timeline.py","protocol.py","designation.py","authority.py","measurements.py","runner.py")
def request_path_import_gate(sources: Mapping[str, str]) -> tuple[bool, str]   # rejects foundry.experiments.long_horizon_bounded.expectations, .expectations, from-package import expectations, named grading helpers; all six keys required

# integrity.py
GATE_NAMES: Final = ("head_equals_final_seal","worktree_clean","seal_descends_from_frozen_core","core_paths_unchanged_since_frozen_core","fr_policy_is_9p2","fr_prompt_hash_frozen","a_policy_is_9p","a_prompt_hash_frozen","output_schema_hash_frozen","f_calls_per_delta_is_2","a_two_calls_no_retry","r_uses_fresh_ledger_per_t","evidence_manifest_frozen","arm_schedule_frozen","ceilings_frozen","answer_key_not_imported_by_request_path","leakage_gate_passes","track_a_regression_passes","scope_closure_regression_passes","historical_artifacts_unchanged","grpc_dns_resolver_is_native","predecessor_raw_evidence_unchanged","r_cumulative_context_within_bounds")
HISTORICAL_ARTIFACT_DIRS: Final = (... 9P v1/v2 longitudinal dirs, 9P2 unseen v1/v2/v3 dirs ...)
PREDECESSOR_RAW_EVIDENCE_SHA = "201198f60c51e16269451e7d582027361d7e8a24"
def preflight(*, git: GitCliLike, commands: CommandRunnerLike, frozen_sha, manifest: Mapping, expectations_bytes: bytes, request_path_sources: Mapping[str,str], leakage: LeakageResult, observed_grpc_dns_resolver: str | None) -> tuple[GateResult, ...]
# post-run deterministic verdicts over a RunResult (I1–I15 per spec §12):
class IntegrityVerdict(FrozenModel): id: str; passed: bool | None; detail: str; applies_to: tuple[Arm, ...]
def integrity_verdicts(run: RunResult) -> tuple[IntegrityVerdict, ...]   # I1..I15; I13/I14 taken from preflight results passed in
def request_only_reference_check(records: tuple[RequestRecord, ...], judgments_by_call: ...) -> tuple[bool, str]   # I10
def r_context_within_bounds() -> tuple[bool, str]   # I13 ⊙: compile R Call-1 requests for T1..T16 via the real assembly path; T16 canonical context <= 100_000 chars
```

- [ ] **Step 1: Leakage tests (RED)** — `needles()` contains every checkpoint id, class label, decision name, expected meaning and requirement sentence, and no Orion section text; `needle_set_sha256()` is over the sorted unnormalized tuple; all nine skeletons render (F/R five-key with `CONTRASTIVE_SYSTEM_INSTRUCTION`, A four-key with `SYSTEM_INSTRUCTION`); the default gate PASSES; mutation: each representative needle injected via `extra_harness_text` FAILS with the needle/skeleton named, while the same phrase inside stand-in evidence content does not fail; `request_path_import_gate` on the six real files PASSES, on a synthetic source importing `.expectations` in each of the 12 forms FAILS, on a mapping missing `runner.py` FAILS.

- [ ] **Step 2: Integrity tests (RED)** — fake `GitCliLike`/`CommandRunnerLike`, a manifest fixture built from T1/T5 values; every gate PASSES on correct input and FAILS on one corruption (dirty tree; changed core path; wrong prompt hash; missing runner source; non-zero pytest exit; resolver `None`/`""`/`"ares"`/`"Native"`; changed path under any historical dir; changed path under the 9P2 v3 dir since `201198f`; `PREDECESSOR_RAW_EVIDENCE_SHA` not an ancestor; R T16 context over 100,000 by monkeypatching the bound). Post-run: build a scripted `RunResult` (T4 fakes) and prove each I1–I15 verdict PASSES on it and FAILS under one mutation each — I1 duplicate root address; I2 a cell with one request; I3 a duplicate request sha (retry shape); I4 a proposal citing a non-request evidence id; I5 a cited predecessor present only in comparison context; I6 an out-of-scope known address; I7 a model SUPERSEDE routed APPLY; I8 an applied AGREE with no matching pending signature; I9 replay mismatch; **I10** — a SUPERSEDE targeting the creating judgment of a claim asserted earlier in the same response (must FAIL), an ASSERT at an address not in `known_addresses` (FAIL), a SUPPORTS of a claim not in `known_claims` (FAIL), evidence not in `request.evidence` (FAIL), and the legitimate correction shape ASSERT-at-known-address + SUPERSEDE-of-known-claim's-creating-judgment (PASS); I11 a superseded judgment missing from the final ledger; I12 receipts/requests count mismatch; I15 an AGREE whose target is outside that T's `EligibleTargets.eligible_judgment_ids`, an AGREE at a non-checkpoint T, and an authority record carrying rationale text beyond `AGREE: <id>`.

- [ ] **Step 3: Run RED** → `ImportError` on both modules.

- [ ] **Step 4: Implement `leakage.py`** — `normalize_leakage_text` imported from `contrastive_unseen.leakage`; skeleton governor with opaque descriptors; scanning after evidence-content substitution; fail closed on first match.

- [ ] **Step 5: Implement `integrity.py`** — gates per spec §12/§15 carried forward from 9P2 (gate 1 = full seal rule: HEAD == frozen sha, single parent == `manifest["harness_code_sha"]`, parent..HEAD names exactly the two prereg files); gate `predecessor_raw_evidence_unchanged`: `git.is_ancestor(PREDECESSOR_RAW_EVIDENCE_SHA, frozen_sha)` and no changed path under `docs/superpowers/experiments/2026-09-13-contrastive-unseen-lifecycle-v3/` since it, and manifest `predecessor_raw_evidence_sha` equals the literal; `historical_artifacts_unchanged` diffs every dir in `HISTORICAL_ARTIFACT_DIRS` from `FROZEN_CORE_SHA` and records each dir's tree hash in the detail; `r_cumulative_context_within_bounds` compiles `assemble_assimilation_request(project_id=..., delta=reconstruction_corpus(t, ...), state=<fresh governor state after ingesting the corpus>, scope=SCOPE)` for t in 1..16 with no reasoner and reports `comparison_context_character_count`. I10 implementation:

```python
def request_only_reference_check(records, judgments_by_call):
    for record, judgments in zip(records, judgments_by_call, strict=True):
        evidence, addresses, claims = set(record.citable_evidence_ids), set(record.known_address_ids), set(record.known_claim_ids)
        creating = set(record.known_claim_creating_judgment_ids)   # add this tuple to the per-call capture in T4's CellRecord (from request.known_claims[*].created_by_judgment_id)
        for j in judgments:
            refs = _references(j)   # (evidence ids, address ids, claim ids, supersede targets) read structurally from the proposal
            if not refs.evidence <= evidence or not refs.addresses <= addresses or not refs.claims <= claims or not refs.targets <= creating:
                return False, f"request-only reference law violated by {j.judgment_id} at {record.arm} T{record.t} call {record.call_number}"
    return True, "every reference resolves against its exact request; no same-response id used"
```

(Because `known_claim_creating_judgment_ids` is captured from the request itself, an id minted while wrapping a sibling draft of the same response can never be in the set.) I15: for each applied human SUPERSEDE, find the `EligibleTargets` of that (arm, t), require target ∈ `eligible_judgment_ids`, a pending model proposal with equal signature earlier in the ledger, route APPLY + `HUMAN_AUTHORITY`, `t in AUTHORITY_CHECKPOINTS`, rationale exactly `AGREE: <pending id>`.

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
    early_window; late_window; decision_names; historical_artifact_dirs: tuple[str, ...]; historical_artifact_tree_hashes: dict[str, str]; lifecycle_project_id; scope
def build_manifest(*, harness_code_sha: str, spec_sha256: str, historical_tree_hashes: Mapping[str, str]) -> ExperimentManifest
def write_preregistration(out_dir: Path, manifest) -> dict[str, str]
def existing_raw_artifacts(out_dir: Path) -> tuple[str, ...]
RAW_ARTIFACT_PATHS  # preflight.json, measurements.json, verdicts.json, report.md, F/{requests,drafts,receipts,decisions,eligible_targets,authorizations,ledger,result}.json, A/..., R/T01..T16/{requests,drafts,receipts,decisions,ledger,result}.json
def write_preflight(out_dir, gates, *, frozen_sha, leakage, observed_grpc_dns_resolver) -> Path
def write_run_artifacts(out_dir, run: RunResult, verdicts: tuple[IntegrityVerdict, ...]) -> tuple[str, ...]   # write-once; secret scan; NOT_RUN cells written
def write_adjudication(out_dir, *, raw_run_commit_sha: str, git: GitCliLike, adjudication: Adjudication) -> tuple[str, ...]
class Adjudication(FrozenModel): checkpoints: dict[Arm, dict[str, bool]] (C02..C16); control_errors: dict[Arm, int]; material_errors: dict[Arm, int]; notes: str
```

- [ ] **Step 1: Tests (RED)** — manifest canonical hash stable across mapping insertion order; `expectations_sha256 == canonical_sha256(expectations_document())`; `corpus_sha256 == timeline.corpus_sha256()`; `write_preregistration` writes exactly two files and refuses if either exists; raw tree from a scripted COMPLETED run equals `RAW_ARTIFACT_PATHS` exactly (48 cells: F/A folders aggregate 16 steps each, R/T01..T16); an aborted run still writes every cell with NOT_RUN results and `measurements.json`; overwrite refusal is all-or-nothing (a stray `R/T09/ledger.json` leaves the tree unchanged); requests preserve exact rendered text and sha; a secret-shaped `rendered_user_request` refuses the whole write, secret-shaped error text is redacted; `verdicts.json` after COMPLETED carries I1–I15 deterministic verdicts (I2 through I15 where computable) and `semantic_checkpoints`, `material_errors`, `control_errors`, `errors_total`, `architecture_selection` all `null`; `report.md` contains `architecture_selection = null (architect adjudication pending)`; `write_adjudication` refuses when `git.head() != raw_run_commit_sha` or the working tree is dirty or the raw files' hashes differ from those at `raw_run_commit_sha` (`git.show_bytes`), and on success writes only `verdicts.json` and `report.md` (all other raw files byte-identical before/after) and computes `select_architecture` from the adjudication plus `measurements.json`; no path under any historical experiment dir is touched (snapshot before/after).

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

**Prepare script** (`main(argv, *, cwd) -> int`): `--out` default `docs/superpowers/experiments/2026-09-13-long-horizon-bounded-memory-v1`; git via `subprocess` only for `status --porcelain` (must be empty), `rev-parse HEAD` (= `harness_code_sha`), `merge-base --is-ancestor <FROZEN_CORE_SHA> HEAD`, `merge-base --is-ancestor <PREDECESSOR_RAW_EVIDENCE_SHA> HEAD`, `show HEAD:<SPEC_PATH>` (must equal working-tree bytes), `rev-parse HEAD:<dir>` for every historical artifact dir (tree hashes into the manifest); refuses if either prereg file exists; writes exactly the two files; prints canonical hashes; no key, no reasoner, no network.

**Run script** (`main(argv, *, cwd, env, reasoner_factory, git, commands) -> int`): mutually exclusive `--preflight-only` | `--live`; `--frozen-sha` (40 lowercase hex) and `--out` required; `observed_grpc_dns_resolver = env.get("GRPC_DNS_RESOLVER")` read once before any gate in both modes; `--preflight-only` evaluates all gates (23 names of T5) with the six real request-path sources, prints the preflight document, writes nothing, never reads `XAI_API_KEY`, never calls the factory, exit 0/3; `--live`: seal files required → no existing raw artifact → all gates → `write_preflight` once → exit 3 on failure with zero calls → only then `env.get("XAI_API_KEY")` (missing → `ABORTED_RUNTIME`/`MISSING_API_KEY` tree, exit 4) → factory (F `XAIContrastiveSemanticReasoner(api_key=..., model="grok-4.6", reasoning_effort="high")`, A `XAISemanticReasoner(...)`, R `XAIContrastiveSemanticReasoner(...)`) → `build_arm_reasoners` → identity-guard wrapper (checks adapter class attributes and fingerprints against the manifest before every forwarded call; `IdentityDrift(RuntimeError)`) → `run_experiment` inside the abort-recording `try` (construction included) → `integrity_verdicts` → `write_run_artifacts` always → exit 0 if COMPLETED else 4. Exit 2 for refusals. Never retry.

- [ ] **Step 1: Tests (RED)** — fakes only (FakeGit with realistic parent/ancestor/changed-path tables incl. the predecessor sha; FakeCommands exit codes; scripted reasoners via injected factory; `PoisonedEnv` answering only `GRPC_DNS_RESOLVER`; sockets blocked): failed preflight never reads the key and never calls the factory; preflight-only writes nothing, constructs nothing, prints 23 gates, `frontier_calls: 0`, `observed_grpc_dns_resolver: "native"`; resolver absent/`ares`/`Native` → exit 3 with only gate 21 failed; passed preflight + missing key → `ABORTED_RUNTIME`, zero calls, full tree; fake live success → full raw tree, 96 request records, 48 COMPLETED cells, `measurements.json` with 96 rows, `verdicts.json` semantic fields null, exit 0; scripted provider failure at position 20 → earlier cells preserved, later NOT_RUN, exit 4; second `--live` with existing `preflight.json` refuses (exit 2) before the factory; raising factory → `ABORTED_RUNTIME` recorded; identity guard: a 9p-v4-fingerprinted fake as F refused at construction, adapter-attribute drift → `IdentityDrift` before any forwarded call; manifest/expectations bytes unchanged after any run; `write_adjudication` end-to-end on the fake run tree with a FakeGit at the raw commit.

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

- [ ] Diff gate against the approved design commit — allowed paths only (this plan, the new package, the two scripts, the new tests):

```bash
git diff --name-only 43e5ea60cd92b700db4c58314a5ce68c50028169...HEAD
git diff --name-only 1f89fc86cda463da676bf45603b86a7dcb458452..HEAD -- src/foundry/domain src/foundry/application src/foundry/ports src/foundry/adapters src/foundry/experiments/longitudinal src/foundry/experiments/contrastive_unseen docs/superpowers/experiments   # must be empty
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
Expected: `all_passed: true`, all 23 gates PASS, `frontier_calls: 0`, `judge_calls: 0`, `human_authorizations: 0`, `observed_grpc_dns_resolver: "native"`, `run_status: null`, no file written, no key read, no network. Also demonstrate fail-closed offline with the resolver absent (`env -u GRPC_DNS_RESOLVER ...`) → exit 3, only `grpc_dns_resolver_is_native` failed, nothing written.
- [ ] Final code review of the seal commit (only two files, parent == `harness_code_sha`) and `superpowers:verification-before-completion` with fresh full pytest/ruff/mypy on the seal HEAD.
- [ ] STOP. Do not run `--live`. Do not push. Live execution requires a new explicit architect authorization after independent verification of the seal.

Allowed final conclusion: **`9P3 long-horizon bounded-memory harness locally verified and sealed; live experiment remains unauthorized pending architect verification.`**

---

## Plan self-review record

1. **Spec coverage:** §1–§2 laws → Global Constraints; §3–§5, §7 corpus → T1 timeline (byte-exact spec-block test); §6 classes and §10 checkpoints/controls/R rules → T1 expectations; §8 arms → T4 (F/R `assimilate_delta`, A reused ablation); §9 order/96 calls → T1 protocol + T4; §10.1 designation → T2; §11/§17 budgets → T1 protocol + T4 budget + T2 ceiling 48; §12 I1–I15 (+ preflight carry-overs, predecessor and historical preservation, I13 offline compile, I14 leakage) → T5; §13 measurements → T3; §14 economy/growth (exact rationals) → T1 expectations + T3 summary; §15 leakage → T5; §16 precedence/`TOKEN_DIFF_FA`/examples → T1 expectations (live runner never calls it; only T6 `write_adjudication`); §18 pre-T authority + I15 → T2 + T4 + T5; §19 freeze discipline → T6/T7/T9; §20 no production changes → Global Constraints 4–6 and the T8 diff gate; §21 non-goals → nothing planned beyond them; §22–§24 → T9 stop conditions.
2. **Red-flag scan:** none of the writing-plans red-flag phrases and no unspecified steps; every code step shows the code or the exact algorithm; the 38 section texts are transcribed from the spec and locked by a byte-exact test.
3. **Type consistency:** `RootDesignation`, `EligibleTargets`, `AuthorizationRecord`, `CallMeasurement`, `TokenSummary`, `CellRecord`, `ArmSummary`, `RunResult`, `LeakageResult`, `GateResult`, `IntegrityVerdict`, `ExperimentManifest`, `Adjudication`, `SelectionInputs/Outcome` are named identically in every task that consumes them; `known_claim_creating_judgment_ids` is added to the T4 per-call capture because T5's I10 consumes it.
4. No task modifies production code, `contrastive_unseen`, `longitudinal`, or any prior experiment directory; the T8 diff gate enforces it.
5. No live model/provider call exists in any step; `--live` is implemented but never invoked; factories are injected in every test.
6. Architecture selection is computed only by `write_adjudication` after the raw-run commit; the live runner and `write_run_artifacts` leave it null.
7. Semantic grading (C02–C16, control errors, material errors) remains architect input to `Adjudication` after the raw freeze.
8. T8/T10 and all fifteen transitions, the approved T9 idempotent-cancellation text, I10 request-only, the 48 authorization ceiling and the 96-call ceiling are locked by T1/T2/T5 tests exactly as frozen in the spec.
9. Raw evidence commit precedes semantic adjudication: `write_adjudication` requires `git.head() == raw_run_commit_sha` and byte-identical raw files.
