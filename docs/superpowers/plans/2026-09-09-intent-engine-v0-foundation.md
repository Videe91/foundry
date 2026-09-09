# Intent Engine v0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic Intent Engine substrate that can represent semantic intent, record immutable events, replay current state, represent gaps and jobs, evaluate closure, and score sealed evaluation fixtures before any model-driven ingestion is added.

**Architecture:** Start as a Python modular monolith. Domain models are immutable Pydantic objects; all state changes enter through typed append-only events; a pure reducer materializes `IntentState`; PostgreSQL persists event streams; closure and package generation are deterministic projections; the evaluation harness is isolated from execution inputs so future AI workers cannot see hidden expectations.

**Tech Stack:** Python 3.12, Pydantic 2.x, SQLAlchemy 2.x, psycopg 3.x, Alembic 1.x, Typer 0.x, PostgreSQL 16, pytest 8.x, pytest-cov, Ruff, mypy, uv, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-09-intent-engine-v0-design.md`

## Global Constraints

The implementation must obey `FOUNDRY_CONSTITUTION.md` and these subsystem requirements copied from the approved design:

1. Research is subordinate to intent and produces evidence only.
2. Every material semantic object has provenance.
3. Authority and confidence are separate fields.
4. Material ambiguity is explicit state, never hidden in prose.
5. Unknowns may remain only if they are known, bounded, and non-blocking.
6. Expensive reasoning is invoked only when deterministic logic or cheaper workers are not trustworthy enough.
7. Worker context is compiled per job and must be bounded.
8. Disagreement among evidence is preserved rather than summarized away.
9. Closure is based on risk and unresolved materiality, not on the absence of all unknowns.
10. Greenfield and brownfield inputs converge into the same canonical intent schema.

v0 will not generate production code, choose full system architecture, deploy infrastructure, operate production systems, train ML models, build a graphical IDE, require a graph database, implement microservices, maintain one persistent super-agent, or attempt to formalize every requirement.

All input enters as an Event. No input mutates canonical state directly.

Events are append-only. The current intent state must be reproducible by replaying the ledger through deterministic reducers.

Authority is independent from confidence.

Whole-project context is forbidden by default.

Research cannot directly create canonical requirements or decisions.

---

## File Map

The deterministic v0 milestone creates this structure:

```text
foundry/
├── .gitignore
├── .python-version
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
├── src/
│   └── foundry/
│       ├── __init__.py
│       ├── cli.py
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── common.py
│       │   ├── semantic.py
│       │   ├── gaps.py
│       │   ├── jobs.py
│       │   ├── events.py
│       │   ├── state.py
│       │   └── closure.py
│       ├── application/
│       │   ├── __init__.py
│       │   ├── reducer.py
│       │   ├── replay.py
│       │   └── package.py
│       ├── ports/
│       │   ├── __init__.py
│       │   └── event_store.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   └── postgres/
│       │       ├── __init__.py
│       │       ├── database.py
│       │       ├── event_store.py
│       │       └── migrations/
│       │           ├── env.py
│       │           └── versions/
│       │               └── 0001_event_streams.py
│       └── evaluation/
│           ├── __init__.py
│           ├── models.py
│           ├── loader.py
│           └── scorer.py
├── evals/
│   └── fixtures/
│       ├── greenfield/
│       │   └── payments_vague/
│       │       ├── input.json
│       │       └── judge.json
│       └── brownfield/
│           └── retry_conflict/
│               ├── input.json
│               └── judge.json
└── tests/
    ├── unit/
    │   ├── test_semantic_models.py
    │   ├── test_gap_job_models.py
    │   ├── test_events.py
    │   ├── test_reducer.py
    │   ├── test_closure.py
    │   ├── test_package.py
    │   └── test_eval_scorer.py
    ├── integration/
    │   └── test_postgres_event_store.py
    └── e2e/
        └── test_replay_to_package.py
```

### Responsibility boundaries

- `domain/`: pure immutable models and deterministic rules; no database, network, model provider, or CLI imports.
- `application/`: orchestration over domain objects; still no provider-specific code.
- `ports/`: protocols that adapters implement.
- `adapters/postgres/`: persistence only.
- `evaluation/`: sealed-fixture loading and scoring only; it never mutates Intent State.
- `evals/fixtures/*/input.json`: information an executor may receive.
- `evals/fixtures/*/judge.json`: hidden expectations used only by the scorer.

---

### Task 1: Bootstrap the Python project and deterministic development environment

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `docker-compose.yml`
- Create: `src/foundry/__init__.py`
- Create: `src/foundry/domain/__init__.py`
- Create: `src/foundry/application/__init__.py`
- Create: `src/foundry/ports/__init__.py`
- Create: `src/foundry/adapters/__init__.py`
- Create: `src/foundry/evaluation/__init__.py`
- Create: `tests/unit/test_package_import.py`

**Interfaces:**
- Consumes: none.
- Produces: installable package `foundry`; `uv run pytest`, `uv run ruff check .`, and `uv run mypy src` become the standard local verification commands.

- [ ] **Step 1: Write the failing import test**

```python
# tests/unit/test_package_import.py

def test_foundry_package_imports() -> None:
    import foundry

    assert foundry.__version__ == "0.1.0"
```

- [ ] **Step 2: Run the test before package setup**

Run:

```bash
pytest tests/unit/test_package_import.py -v
```

Expected: FAIL because `foundry` is not installed/importable yet.

- [ ] **Step 3: Create package configuration**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25,<2"]
build-backend = "hatchling.build"

[project]
name = "foundry-system"
version = "0.1.0"
description = "Foundry autonomous computational-systems factory"
requires-python = ">=3.12"
dependencies = [
  "alembic>=1.13,<2",
  "pydantic>=2.9,<3",
  "psycopg[binary]>=3.2,<4",
  "sqlalchemy>=2.0,<3",
  "typer>=0.12,<1",
]

[dependency-groups]
dev = [
  "mypy>=1.11,<2",
  "pytest>=8.3,<9",
  "pytest-cov>=5,<7",
  "ruff>=0.6,<1",
  "testcontainers[postgres]>=4.8,<5",
]

[project.scripts]
foundry = "foundry.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/foundry"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["foundry"]
```

Create `.python-version`:

```text
3.12
```

Create `.gitignore`:

```text
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.env
*.pyc
.DS_Store
```

Create `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: foundry
      POSTGRES_PASSWORD: foundry
      POSTGRES_DB: foundry
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U foundry -d foundry"]
      interval: 2s
      timeout: 2s
      retries: 15
```

Create `src/foundry/__init__.py`:

```python
__version__ = "0.1.0"
```

Create empty package marker files for the directories listed above.

- [ ] **Step 4: Install and verify tooling**

Run:

```bash
uv sync --all-groups
uv run pytest tests/unit/test_package_import.py -v
uv run ruff check .
uv run mypy src
```

Expected: all commands PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .python-version .gitignore docker-compose.yml src tests/unit/test_package_import.py
git commit -m "chore: bootstrap Foundry Python project"
```

---

### Task 2: Define the canonical semantic vocabulary, provenance, authority, and relations

**Files:**
- Create: `src/foundry/domain/common.py`
- Create: `src/foundry/domain/semantic.py`
- Test: `tests/unit/test_semantic_models.py`

**Interfaces:**
- Consumes: Pydantic from Task 1.
- Produces: `Authority`, `LifecycleStatus`, `RiskLevel`, `Materiality`, `Provenance`, `Relation`, `SemanticObject` discriminated union, and concrete semantic object models used by events, state, closure, and evaluation.

- [ ] **Step 1: Write tests that lock the constitutional metadata rules**

```python
# tests/unit/test_semantic_models.py
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.semantic import Claim, Requirement, SemanticKind


def test_claim_keeps_authority_confidence_and_provenance_separate() -> None:
    provenance = Provenance(
        source_kind=SourceKind.CODE,
        source_ref="repo://envd/rpc.go#L10-L20",
        source_event_ids=("EVT-1",),
    )
    claim = Claim(
        id="CLAIM-1",
        project_id="PROJ-1",
        statement="Legacy dispatch uses three retries.",
        authority=Authority.INFERRED,
        confidence=0.98,
        provenance=provenance,
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
    )

    assert claim.kind is SemanticKind.CLAIM
    assert claim.authority is Authority.INFERRED
    assert claim.confidence == 0.98
    assert claim.provenance.source_ref.endswith("#L10-L20")


def test_confidence_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        Claim(
            id="CLAIM-2",
            project_id="PROJ-1",
            statement="Invalid confidence.",
            authority=Authority.INFERRED,
            confidence=1.01,
            provenance=Provenance(
                source_kind=SourceKind.HUMAN,
                source_ref="human://owner",
                source_event_ids=("EVT-2",),
            ),
            created_at=datetime(2026, 9, 9, tzinfo=UTC),
        )


def test_material_requirement_can_demand_measurement_and_verification() -> None:
    requirement = Requirement(
        id="REQ-1",
        project_id="PROJ-1",
        statement="Regional loss must not materially interrupt service.",
        authority=Authority.CANONICAL,
        confidence=1.0,
        provenance=Provenance(
            source_kind=SourceKind.HUMAN,
            source_ref="human://owner",
            source_event_ids=("EVT-3",),
        ),
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
        requires_metric=True,
        requires_verification=True,
    )

    assert requirement.requires_metric is True
    assert requirement.requires_verification is True
```

- [ ] **Step 2: Run tests to verify the models do not exist**

Run:

```bash
uv run pytest tests/unit/test_semantic_models.py -v
```

Expected: FAIL on imports from `foundry.domain.common` and `foundry.domain.semantic`.

- [ ] **Step 3: Implement common immutable domain types**

Create `src/foundry/domain/common.py` with these exact public types:

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Authority(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    PROPOSED = "PROPOSED"
    CANONICAL = "CANONICAL"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LifecycleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SourceKind(StrEnum):
    HUMAN = "HUMAN"
    DOCUMENT = "DOCUMENT"
    CODE = "CODE"
    TEST = "TEST"
    RUNTIME = "RUNTIME"
    RESEARCH = "RESEARCH"
    SYSTEM = "SYSTEM"


class Materiality(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RelationType(StrEnum):
    SUPPORTS = "SUPPORTS"
    CHALLENGES = "CHALLENGES"
    DERIVED_FROM = "DERIVED_FROM"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    REQUIRES = "REQUIRES"
    CONSTRAINS = "CONSTRAINS"
    MEASURED_BY = "MEASURED_BY"
    VERIFIED_BY = "VERIFIED_BY"
    SUPERSEDES = "SUPERSEDES"
    AFFECTS = "AFFECTS"
    RELATES_TO = "RELATES_TO"


class Provenance(FrozenModel):
    source_kind: SourceKind
    source_ref: str = Field(min_length=1)
    source_event_ids: tuple[str, ...] = ()


class Relation(FrozenModel):
    relation_type: RelationType
    target_id: str = Field(min_length=1)


class TemporalMetadata(FrozenModel):
    created_at: datetime
```

- [ ] **Step 4: Implement the explicit semantic object family**

Create `src/foundry/domain/semantic.py`. Define `SemanticKind` with these values:

```text
INTENT, GOAL, ACTOR, OUTCOME, REQUIREMENT, CONSTRAINT, NON_GOAL,
DECISION, PREFERENCE, ASSUMPTION, CLAIM, EVIDENCE, UNKNOWN, QUESTION,
CONFLICT, RISK, METRIC, CONTRACT, VERIFICATION_OBLIGATION,
AUTHORITY_RECORD, AMENDMENT
```

Use a shared immutable base:

```python
class SemanticBase(FrozenModel):
    id: str
    project_id: str
    kind: SemanticKind
    revision: int = Field(default=1, ge=1)
    lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE
    authority: Authority
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance
    created_at: datetime
    scope: tuple[str, ...] = ()
    relations: tuple[Relation, ...] = ()
```

Concrete classes must use literal `kind` defaults and the following minimum fields:

```text
Intent: mission
Goal: statement
Actor: name, description
Outcome: statement
Requirement: statement, materiality, requires_metric, metric_exempt_reason,
             requires_verification, verification_exempt_reason
Constraint: statement
NonGoal: statement
Decision: statement, rationale
Preference: statement
Assumption: statement, risk_level
Claim: statement
Evidence: statement, supported_claim_ids, challenged_claim_ids, source_type,
          retrieved_at, freshness_note, limitations
Unknown: question, blocking
Question: prompt, target_object_ids
Conflict: statement, object_ids, resolved
Risk: statement, risk_level, likelihood
Metric: name, definition, target
Contract: statement, observable
VerificationObligation: statement, target_object_ids, method_class
AuthorityRecord: subject_id, authorized_by, rationale
Amendment: subject_id, change_statement, rationale
```

#### Architect-approved semantic field semantics

- `Requirement.materiality` is required and has no default. Foundry must not silently infer materiality.
- Evidence source classification is stored only in `Evidence.provenance.source_kind`; `Evidence` does not duplicate a `source_type` field.
- `Evidence.supported_claim_ids` and `challenged_claim_ids` default to empty tuples.
- `Evidence.retrieved_at` is required.
- `Evidence.freshness_note` is optional.
- `Evidence.limitations` is a tuple of zero or more limitation statements.
- `Risk.likelihood`, when present, is a probability in `[0.0, 1.0]`; `None` means no defensible probability estimate exists.

Expose a Pydantic discriminated union named `SemanticObject` using the `kind` discriminator so persisted JSON can be parsed back into the correct concrete type.

- [ ] **Step 5: Run semantic tests and static checks**

Run:

```bash
uv run pytest tests/unit/test_semantic_models.py -v
uv run ruff check src/foundry/domain tests/unit/test_semantic_models.py
uv run mypy src/foundry/domain
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/foundry/domain/common.py src/foundry/domain/semantic.py tests/unit/test_semantic_models.py
git commit -m "feat: define Intent Engine semantic vocabulary"
```

---

### Task 3: Make gaps and bounded jobs first-class domain objects

**Files:**
- Create: `src/foundry/domain/gaps.py`
- Create: `src/foundry/domain/jobs.py`
- Test: `tests/unit/test_gap_job_models.py`

**Interfaces:**
- Consumes: `Materiality`, `RiskLevel`, `FrozenModel` from Task 2.
- Produces: `Gap`, `GapKind`, `GapStatus`, `Job`, `JobType`, `JobStatus`,
and `ExecutorClass`.

#### Architect-approved job contract semantics

- Task 3 does not introduce a `VerificationRequirement` domain type.
- `Job.verification_requirement` is the bounded acceptance condition for a worker job and remains a non-empty string in v0.
- `VerificationObligation` remains the separate semantic object describing what the resulting system must eventually prove.
- `Job.output_schema_ref` must be non-empty.
- `Job.permitted_executors` must contain at least one executor class.
- `Job.max_context_tokens` must be greater than zero.
- `Job.budget_usd` must be non-negative.
- `Job.attempt` must be non-negative.

- [ ] **Step 1: Write tests for blocking gaps and bounded job economics**

```python
# tests/unit/test_gap_job_models.py
from foundry.domain.common import Materiality, RiskLevel
from foundry.domain.gaps import Gap, GapKind, GapStatus
from foundry.domain.jobs import ExecutorClass, Job, JobStatus, JobType


def test_gap_carries_materiality_scope_and_blocking_state() -> None:
    gap = Gap(
        id="GAP-1",
        project_id="PROJ-1",
        kind=GapKind.AMBIGUITY,
        description="The term fast has no threshold.",
        materiality=Materiality.HIGH,
        risk=RiskLevel.HIGH,
        affected_object_ids=("REQ-1",),
        blocking=True,
    )

    assert gap.status is GapStatus.OPEN
    assert gap.blocking is True


def test_job_has_bounded_context_budget_and_executor_classes() -> None:
    job = Job(
        id="JOB-1",
        project_id="PROJ-1",
        gap_id="GAP-1",
        job_type=JobType.AMBIGUITY_ANALYSIS,
        target_object_ids=("REQ-1",),
        output_schema_ref="foundry://schemas/ambiguity-result/v1",
        risk=RiskLevel.HIGH,
        max_context_tokens=8_000,
        permitted_executors=(ExecutorClass.CHEAP_MODEL, ExecutorClass.STRONG_MODEL),
        budget_usd=0.25,
        verification_requirement="Must return a schema-valid ambiguity classification.",
    )

    assert job.status is JobStatus.PENDING
    assert ExecutorClass.FRONTIER_MODEL not in job.permitted_executors
```

- [ ] **Step 2: Verify failure**

Run:

```bash
uv run pytest tests/unit/test_gap_job_models.py -v
```

Expected: FAIL because the gap/job modules do not exist.

- [ ] **Step 3: Implement gap models**

`GapKind` must include:

```text
MISSING_INFORMATION
AMBIGUITY
CONTRADICTION
UNSUPPORTED_ASSUMPTION
MISSING_AUTHORITY
MISSING_SUCCESS_METRIC
MISSING_VERIFICATION_OBLIGATION
UNRESOLVED_RISK
STALE_EVIDENCE
INSUFFICIENT_EVIDENCE
UNDERSPECIFIED_SCOPE
UNRESOLVED_DEPENDENCY
WORKER_DIVERGENCE
CONTEXT_FAILURE
```

`GapStatus` must include `OPEN`, `RESOLVED`, `WAIVED`.

`Gap` fields:

```python
id: str
project_id: str
kind: GapKind
description: str
materiality: Materiality
risk: RiskLevel
affected_object_ids: tuple[str, ...]
blocking: bool
status: GapStatus = GapStatus.OPEN
resolution_event_id: str | None = None
```

- [ ] **Step 4: Implement job models**

`ExecutorClass` must exactly include:

```text
DETERMINISTIC
CHEAP_MODEL
STANDARD_MODEL
STRONG_MODEL
FRONTIER_MODEL
HUMAN
```

`JobType` must include the job classes from the spec plus `CONTEXT_RECOMPILE`:

```text
DETERMINISTIC_EXTRACTION
SEMANTIC_CLASSIFICATION
AMBIGUITY_ANALYSIS
CONTRADICTION_ANALYSIS
RESEARCH_PLANNING
EVIDENCE_COLLECTION
EVIDENCE_RECONCILIATION
REQUIREMENT_REFINEMENT
METRIC_DESIGN
VERIFICATION_OBLIGATION_DESIGN
TRADE_OFF_ANALYSIS
STRONG_REASONING_RESOLUTION
HUMAN_CLARIFICATION
HUMAN_AUTHORIZATION
CONTEXT_RECOMPILE
```

`JobStatus` must include `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `ESCALATED`, `CANCELLED`.

`Job` fields:

```python
id: str
project_id: str
gap_id: str
a job_type: JobType  # use the field name `job_type`; do not include the leading `a`
target_object_ids: tuple[str, ...]
output_schema_ref: str
risk: RiskLevel
max_context_tokens: int = Field(gt=0)
permitted_executors: tuple[ExecutorClass, ...]
budget_usd: float = Field(ge=0.0)
verification_requirement: str
status: JobStatus = JobStatus.PENDING
attempt: int = Field(default=0, ge=0)
```

In the actual code, the declaration is exactly `job_type: JobType`; the explanatory line above intentionally names the field and is not copied literally.

- [ ] **Step 5: Run tests and static checks**

```bash
uv run pytest tests/unit/test_gap_job_models.py -v
uv run ruff check src/foundry/domain tests/unit/test_gap_job_models.py
uv run mypy src/foundry/domain
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/foundry/domain/gaps.py src/foundry/domain/jobs.py tests/unit/test_gap_job_models.py
git commit -m "feat: model intent gaps and bounded jobs"
```

---

### Task 4: Define immutable events and a pure deterministic Intent State reducer

**Files:**
- Create: `src/foundry/domain/events.py`
- Create: `src/foundry/domain/state.py`
- Create: `src/foundry/application/reducer.py`
- Create: `src/foundry/application/replay.py`
- Test: `tests/unit/test_events.py`
- Test: `tests/unit/test_reducer.py`

**Interfaces:**
- Consumes: semantic objects from Task 2; gaps/jobs from Task 3.
- Produces: `EventType`, `EventEnvelope`, typed event payloads, `StoredEvent`, `IntentState`, `reduce_event(state, stored_event)`, and `replay(project_id, events)`.

#### Architect-approved event and state semantics

- Raw document, artifact, and research-result events use a typed `SourceReferencePayload`; they do not directly create semantic truth.
- `GAP_WAIVED` is an explicit event because waiver can affect closure and must be authorized and historically visible.
- Gap resolution/waiver stores the current envelope's event ID as `resolution_event_id`; the payload does not duplicate that ID.
- Semantic-object event types are validated against an explicit expected `SemanticKind`.
- `AMBIGUITY_DETECTED` carries an ambiguity `GapPayload` but only `GAP_RECORDED` places that gap into current state.
- Embedded semantic objects, gaps, and jobs must belong to the same project as the enclosing event.
- `REQUIREMENT_SUPERSEDED` marks the old requirement lifecycle `SUPERSEDED` and increments its object revision; both old and replacement requirements must already exist.
- `IntentState` uses read-only mappings and copy-on-write reduction so nested state cannot be mutated through a frozen model.
- Replay consumes event order exactly as supplied and never repairs or sorts a broken stream.
- Every `SemanticKind` that may exist in current Intent State has exactly one approved event path: specialized kinds use dedicated events, and remaining kinds use `SEMANTIC_OBJECT_RECORDED`.
- `SEMANTIC_OBJECT_RECORDED` may carry only generic semantic kinds. It cannot bypass specialized transitions such as claim inference, requirement canonicalization, or metric definition.
- Recording an `AuthorityRecord` or `Amendment` does not automatically mutate the referenced subject; later explicit events still own those transitions.

- [ ] **Step 1: Write event serialization tests**

```python
# tests/unit/test_events.py
from datetime import UTC, datetime

from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.events import EventEnvelope, EventType, SemanticObjectPayload, parse_event
from foundry.domain.semantic import Claim


def test_event_round_trip_preserves_typed_semantic_payload() -> None:
    claim = Claim(
        id="CLAIM-1",
        project_id="PROJ-1",
        statement="Retries are three.",
        authority=Authority.INFERRED,
        confidence=0.9,
        provenance=Provenance(
            source_kind=SourceKind.CODE,
            source_ref="repo://svc/retry.py#L1-L5",
            source_event_ids=("EVT-1",),
        ),
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    event = EventEnvelope(
        event_id="EVT-2",
        project_id="PROJ-1",
        event_type=EventType.CLAIM_INFERRED,
        occurred_at=datetime(2026, 9, 9, tzinfo=UTC),
        payload=SemanticObjectPayload(object=claim),
    )

    restored = parse_event(event.model_dump(mode="json"))

    assert restored == event
    assert isinstance(restored.payload, SemanticObjectPayload)
    assert isinstance(restored.payload.object, Claim)
```

- [ ] **Step 2: Write reducer replay tests**

```python
# tests/unit/test_reducer.py
from datetime import UTC, datetime

from foundry.application.replay import replay
from foundry.domain.common import Authority, Provenance, SourceKind
from foundry.domain.events import EventEnvelope, EventType, SemanticObjectPayload, StoredEvent
from foundry.domain.semantic import Claim


def test_replay_is_deterministic() -> None:
    claim = Claim(
        id="CLAIM-1",
        project_id="PROJ-1",
        statement="Retries are three.",
        authority=Authority.INFERRED,
        confidence=0.9,
        provenance=Provenance(
            source_kind=SourceKind.CODE,
            source_ref="repo://svc/retry.py#L1-L5",
            source_event_ids=("EVT-1",),
        ),
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    event = StoredEvent(
        sequence=1,
        event=EventEnvelope(
            event_id="EVT-2",
            project_id="PROJ-1",
            event_type=EventType.CLAIM_INFERRED,
            occurred_at=datetime(2026, 9, 9, tzinfo=UTC),
            payload=SemanticObjectPayload(object=claim),
        ),
    )

    first = replay("PROJ-1", [event])
    second = replay("PROJ-1", [event])

    assert first == second
    assert first.objects["CLAIM-1"] == claim
    assert first.last_sequence == 1
```

- [ ] **Step 3: Verify failure**

Run:

```bash
uv run pytest tests/unit/test_events.py tests/unit/test_reducer.py -v
```

Expected: FAIL because event/state/reducer modules do not exist.

- [ ] **Step 4: Implement the typed event envelope**

`EventType` must include all initial spec events plus the job lifecycle events needed by the persistent job model:

```text
USER_STATED_INTENT
DOCUMENT_ADDED
ARTIFACT_CONNECTED
RESEARCH_RESULT_RECEIVED
CLAIM_INFERRED
EVIDENCE_ATTACHED
CONFLICT_DETECTED
AMBIGUITY_DETECTED
UNKNOWN_IDENTIFIED
HUMAN_DECISION_RECORDED
REQUIREMENT_CANONICALIZED
REQUIREMENT_SUPERSEDED
CONSTRAINT_DISCOVERED
ASSUMPTION_IDENTIFIED
RISK_IDENTIFIED
SUCCESS_METRIC_DEFINED
VERIFICATION_OBLIGATION_DEFINED
SEMANTIC_OBJECT_RECORDED
GAP_RECORDED
GAP_RESOLVED
GAP_WAIVED
JOB_CREATED
JOB_STATUS_CHANGED
INTENT_CLOSURE_REACHED
INTENT_REOPENED
```

Define payload models:

```python
class UserStatedIntentPayload(FrozenModel):
    text: str
    actor_id: str


class SourceReferencePayload(FrozenModel):
    source_ref: str = Field(min_length=1)


class SemanticObjectPayload(FrozenModel):
    object: SemanticObject


class GapPayload(FrozenModel):
    gap: Gap


class GapResolvedPayload(FrozenModel):
    gap_id: str


class GapWaivedPayload(FrozenModel):
    gap_id: str
    reason: str = Field(min_length=1)
    authorized_by: str = Field(min_length=1)


class JobPayload(FrozenModel):
    job: Job


class JobStatusChangedPayload(FrozenModel):
    job_id: str
    status: JobStatus
    attempt: int = Field(ge=0)


class SupersessionPayload(FrozenModel):
    object_id: str
    superseded_by: str
    reason: str


class ClosurePayload(FrozenModel):
    scope: str
    package_revision: int


class ReopenPayload(FrozenModel):
    scope: str
    reason: str
```

`EventEnvelope` fields:

```python
event_id: str
project_id: str
event_type: EventType
occurred_at: datetime
correlation_id: str | None = None
causation_id: str | None = None
payload: EventPayload
```

Create an explicit `EVENT_PAYLOAD_TYPES: dict[EventType, type[FrozenModel]]` mapping and `parse_event(raw: Mapping[str, object]) -> EventEnvelope` that validates the payload against the event type before constructing the envelope. Do not accept arbitrary dictionaries as validated payloads.

`StoredEvent` fields are `sequence: int = Field(ge=1)` and `event: EventEnvelope`.

- [ ] **Step 5: Implement current Intent State and pure reducer**

`IntentState`:

```python
class IntentState(FrozenModel):
    project_id: str
    revision: int = Field(default=0, ge=0)
    last_sequence: int = Field(default=0, ge=0)
    source_events: tuple[str, ...] = ()
    objects: Mapping[str, SemanticObject] = Field(default_factory=dict)
    gaps: Mapping[str, Gap] = Field(default_factory=dict)
    jobs: Mapping[str, Job] = Field(default_factory=dict)
    closed_scopes: Mapping[str, int] = Field(default_factory=dict)
```

The reducer must:

- reject events from another project,
- reject non-contiguous sequence numbers,
- add or replace semantic objects only through semantic-object events,
- record gaps through `GAP_RECORDED`,
- resolve gaps through `GAP_RESOLVED`,
- waive gaps through `GAP_WAIVED`,
- record jobs through `JOB_CREATED`,
- update job status through `JOB_STATUS_CHANGED`,
- mark scope closure through `INTENT_CLOSURE_REACHED`,
- remove scope closure through `INTENT_REOPENED`,
- preserve the original event IDs in `source_events`,
- increment `revision` once per reduced event.

The reducer signature is:

```python
def reduce_event(state: IntentState, stored_event: StoredEvent) -> IntentState:
    ...
```

`replay` signature is:

```python
def replay(project_id: str, events: Iterable[StoredEvent]) -> IntentState:
    state = IntentState(project_id=project_id)
    for stored_event in events:
        state = reduce_event(state, stored_event)
    return state
```

- [ ] **Step 6: Add rejection tests for wrong project and sequence gaps**

Add tests asserting `ValueError` for a `StoredEvent(sequence=2, ...)` applied to a fresh state and for an event whose `project_id` differs from the state.

- [ ] **Step 7: Run tests and static checks**

```bash
uv run pytest tests/unit/test_events.py tests/unit/test_reducer.py -v
uv run ruff check src/foundry/domain src/foundry/application tests/unit
uv run mypy src/foundry/domain src/foundry/application
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/foundry/domain/events.py src/foundry/domain/state.py src/foundry/application/reducer.py src/foundry/application/replay.py tests/unit/test_events.py tests/unit/test_reducer.py
git commit -m "feat: add immutable event model and deterministic replay"
```

---

### Task 5: Persist append-only event streams in PostgreSQL with optimistic concurrency

**Files:**
- Create: `src/foundry/ports/event_store.py`
- Create: `src/foundry/adapters/postgres/database.py`
- Create: `src/foundry/adapters/postgres/event_store.py`
- Create: `src/foundry/adapters/postgres/migrations/env.py`
- Create: `src/foundry/adapters/postgres/migrations/versions/0001_event_streams.py`
- Create: `alembic.ini`
- Test: `tests/integration/test_postgres_event_store.py`

**Interfaces:**
- Consumes: `EventEnvelope`, `StoredEvent`, `parse_event` from Task 4.
- Produces: `EventStore` protocol and `PostgresEventStore` implementation with `append`, `load`, and `current_sequence`.

#### Architect-approved persistence semantics

- `intent_events.event_document` stores the complete canonical serialized `EventEnvelope`; indexed columns are persistence metadata around that document.
- Event rows are protected as append-only by PostgreSQL itself; UPDATE, DELETE, and TRUNCATE are rejected.
- `intent_event_streams.current_sequence` is a mutable concurrency cursor, not historical semantic truth.
- Event sequences are monotonic independently per project and are allocated under a PostgreSQL row lock.
- `event_id` is globally unique.
- An existing event ID raises `DuplicateEventError` even if `expected_sequence` is also stale.
- Append is atomic: failure cannot advance the stream cursor or leave a partial event.
- Testcontainers must explicitly use the psycopg 3 driver; Foundry does not add psycopg2.
- Integration verification uses real PostgreSQL 16 and must not be replaced by SQLite or mocks.

#### Persistence falsification and identity integrity

- Sequential stale-sequence tests are not sufficient evidence of PostgreSQL locking; the integration suite exercises simultaneous same-project writers.
- Global `event_id` uniqueness is exercised under simultaneous cross-project inserts so the database unique constraint is verified as the race-safe backstop.
- The canonical JSONB `EventEnvelope` and indexed persistence identity columns (`project_id`, `event_id`, `event_type`, `occurred_at`) are constrained not to contradict one another.
- Full semantic EventEnvelope validation remains the responsibility of `parse_event`; PostgreSQL does not duplicate the complete semantic schema.

- [ ] **Step 1: Write the event-store contract test**

Use `PostgresContainer("postgres:16-alpine", driver="psycopg")` so the integration test uses real PostgreSQL 16 with psycopg 3. The test must verify:

1. first append returns sequence `1`,
2. second append returns sequence `2`,
3. `load` returns events in sequence order,
4. appending with stale `expected_sequence` raises `ConcurrencyError`,
5. inserting the same `event_id` twice raises `DuplicateEventError`.

The test should construct `USER_STATED_INTENT` events because they do not depend on semantic normalization.

- [ ] **Step 2: Verify failure**

Run:

```bash
uv run pytest tests/integration/test_postgres_event_store.py -v
```

Expected: FAIL because the event-store port and adapter do not exist.

- [ ] **Step 3: Define the persistence port**

Create `src/foundry/ports/event_store.py`:

```python
from collections.abc import Sequence
from typing import Protocol

from foundry.domain.events import EventEnvelope, StoredEvent


class ConcurrencyError(RuntimeError):
    pass


class DuplicateEventError(RuntimeError):
    pass


class EventStore(Protocol):
    def append(self, event: EventEnvelope, expected_sequence: int) -> StoredEvent: ...

    def load(self, project_id: str, after_sequence: int = 0) -> Sequence[StoredEvent]: ...

    def current_sequence(self, project_id: str) -> int: ...
```

- [ ] **Step 4: Create the schema migration**

The first migration must create exactly two tables:

```sql
CREATE TABLE intent_event_streams (
    project_id TEXT PRIMARY KEY,
    current_sequence BIGINT NOT NULL CHECK (current_sequence >= 0)
);

CREATE TABLE intent_events (
    project_id TEXT NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence >= 1),
    event_id TEXT NOT NULL,
    UNIQUE (event_id) -- named uq_intent_events_event_id,
    event_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    event_document JSONB NOT NULL,
    PRIMARY KEY (project_id, sequence),
    FOREIGN KEY (project_id) REFERENCES intent_event_streams(project_id)
);

CREATE INDEX ix_intent_events_project_type
ON intent_events(project_id, event_type);
```

The down migration drops `intent_events` before `intent_event_streams`.

- [ ] **Step 5: Implement transactional append**

`PostgresEventStore.append` must execute in one transaction:

1. ensure a stream row exists with sequence 0 using `INSERT ... ON CONFLICT DO NOTHING`,
2. lock the stream row using `SELECT ... FOR UPDATE`,
3. compare stored sequence with `expected_sequence`,
4. compute `next_sequence = expected_sequence + 1`,
5. insert the immutable event JSON document,
6. update stream sequence,
7. commit and return `StoredEvent(sequence=next_sequence, event=event)`.

Map PostgreSQL unique-constraint failure on `event_id` to `DuplicateEventError`.

`load(project_id, after_sequence)` must order by `sequence ASC` and reconstruct each event using `parse_event`.

There must be no update or delete API for event rows.

- [ ] **Step 6: Run migration and integration tests**

Run:

```bash
uv run pytest tests/integration/test_postgres_event_store.py -v
uv run ruff check src/foundry/ports src/foundry/adapters tests/integration
uv run mypy src/foundry/ports src/foundry/adapters
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini src/foundry/ports src/foundry/adapters/postgres tests/integration/test_postgres_event_store.py
git commit -m "feat: persist append-only intent event streams"
```

---

### Task 6: Implement deterministic closure evaluation and Canonical Intent Package projection

**Files:**
- Create: `src/foundry/domain/closure.py`
- Create: `src/foundry/application/package.py`
- Test: `tests/unit/test_closure.py`
- Test: `tests/unit/test_package.py`

**Interfaces:**
- Consumes: `IntentState`, semantic objects, relations, gaps from Tasks 2-4.
- Produces: `ClosureResult`, `ClosureBlocker`, `evaluate_closure(state, scope)`, `CanonicalIntentPackage`, `build_intent_package(state, scope)`.

- [ ] **Step 1: Write closure tests for the constitutional gates**

Create tests covering these exact cases:

1. an open blocking gap prevents closure,
2. a non-blocking low-risk unknown does not prevent closure,
3. an active material requirement whose authority is not `CANONICAL` prevents closure,
4. a requirement with `requires_metric=True` and no `MEASURED_BY` relation prevents closure unless `metric_exempt_reason` is non-empty,
5. a requirement with `requires_verification=True` and no `VERIFIED_BY` relation prevents closure unless `verification_exempt_reason` is non-empty,
6. an active high/critical-risk assumption prevents closure unless a resolved or waived gap explicitly controls it,
7. an unresolved `Conflict` prevents closure.

- [ ] **Step 2: Verify closure tests fail**

```bash
uv run pytest tests/unit/test_closure.py -v
```

Expected: FAIL because `closure.py` does not exist.

- [ ] **Step 3: Implement closure result models and deterministic evaluator**

Use:

```python
class ClosureBlocker(FrozenModel):
    code: str
    object_ids: tuple[str, ...]
    message: str


class ClosureResult(FrozenModel):
    scope: str
    closed: bool
    blockers: tuple[ClosureBlocker, ...]
```

`evaluate_closure(state: IntentState, scope: str) -> ClosureResult` must inspect only objects/gaps whose scope is empty or contains the requested scope. Empty scope means project-wide applicability.

Use stable blocker codes:

```text
OPEN_BLOCKING_GAP
NON_CANONICAL_REQUIREMENT
MISSING_METRIC
MISSING_VERIFICATION_OBLIGATION
UNCONTROLLED_HIGH_RISK_ASSUMPTION
UNRESOLVED_CONFLICT
BLOCKING_UNKNOWN
```

Sort blockers by `(code, object_ids)` before returning them so replay and tests are deterministic.

- [ ] **Step 4: Write Canonical Intent Package projection tests**

The test must construct a closed state with an `Intent`, `Goal`, `Requirement`, `Metric`, and `VerificationObligation`, then assert the package:

- has the same project ID,
- uses `state.revision` as `intent_version`,
- includes only canonical/active obligations in canonical sections,
- preserves assumptions, claims, evidence, conflicts, and unknowns in epistemic sections,
- includes `source_events` as history references,
- cannot be built when `evaluate_closure(...).closed` is false.

- [ ] **Step 5: Implement Canonical Intent Package as a projection, not new truth**

The package model must group IDs rather than duplicating mutable semantic content across multiple stores. Use:

```python
class CanonicalIntentPackage(FrozenModel):
    project_id: str
    intent_version: int
    scope: str
    purpose_ids: tuple[str, ...]
    boundary_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]
    canonical_decision_ids: tuple[str, ...]
    proposed_decision_ids: tuple[str, ...]
    superseded_decision_ids: tuple[str, ...]
    epistemic_ids: tuple[str, ...]
    quality_ids: tuple[str, ...]
    governance_ids: tuple[str, ...]
    history_event_ids: tuple[str, ...]
```

`build_intent_package` must call `evaluate_closure` and raise `IntentNotClosedError` with the blocker codes if closure fails.

- [ ] **Step 6: Run tests and static checks**

```bash
uv run pytest tests/unit/test_closure.py tests/unit/test_package.py -v
uv run ruff check src/foundry/domain/closure.py src/foundry/application/package.py tests/unit
uv run mypy src/foundry/domain/closure.py src/foundry/application/package.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/foundry/domain/closure.py src/foundry/application/package.py tests/unit/test_closure.py tests/unit/test_package.py
git commit -m "feat: evaluate intent closure and project canonical package"
```

---

### Task 7: Build the sealed evaluation schema and deterministic scorer

**Files:**
- Create: `src/foundry/evaluation/models.py`
- Create: `src/foundry/evaluation/loader.py`
- Create: `src/foundry/evaluation/scorer.py`
- Create: `evals/fixtures/greenfield/payments_vague/input.json`
- Create: `evals/fixtures/greenfield/payments_vague/judge.json`
- Create: `evals/fixtures/brownfield/retry_conflict/input.json`
- Create: `evals/fixtures/brownfield/retry_conflict/judge.json`
- Test: `tests/unit/test_eval_scorer.py`

**Interfaces:**
- Consumes: `GapKind` and fixture JSON.
- Produces: `EvalInput`, `EvalExpectation`, `EvalPrediction`, `EvalCost`, `EvalScore`, `load_input`, `load_judge`, and `score_prediction`.

- [ ] **Step 1: Write scoring tests before fixture implementation**

```python
# tests/unit/test_eval_scorer.py
from foundry.domain.gaps import GapKind
from foundry.evaluation.models import (
    EvalExpectation,
    EvalPrediction,
    ExpectedGap,
    PredictedGap,
)
from foundry.evaluation.scorer import score_prediction


def test_scorer_counts_critical_hits_misses_and_false_gaps() -> None:
    expectation = EvalExpectation(
        expected_gaps=(
            ExpectedGap(
                fingerprint="AMBIGUITY:REQ-speed",
                kind=GapKind.AMBIGUITY,
                critical=True,
            ),
            ExpectedGap(
                fingerprint="MISSING_AUTHORITY:REQ-region",
                kind=GapKind.MISSING_AUTHORITY,
                critical=True,
            ),
        ),
        forbidden_gap_fingerprints=("CONTRADICTION:REQ-speed",),
    )
    prediction = EvalPrediction(
        gaps=(
            PredictedGap(
                fingerprint="AMBIGUITY:REQ-speed",
                kind=GapKind.AMBIGUITY,
            ),
            PredictedGap(
                fingerprint="CONTRADICTION:REQ-speed",
                kind=GapKind.CONTRADICTION,
            ),
        )
    )

    score = score_prediction(expectation, prediction)

    assert score.critical_gaps_detected == 1
    assert score.critical_gaps_missed == 1
    assert score.false_gaps == 1
```

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/unit/test_eval_scorer.py -v
```

Expected: FAIL because evaluation modules do not exist.

- [ ] **Step 3: Implement sealed-fixture models**

Use separate models for executor-visible input and judge-only expectations:

```python
class EvalInput(FrozenModel):
    fixture_id: str
    family: str
    project_id: str
    events: tuple[dict[str, object], ...]
    artifact_refs: tuple[str, ...] = ()


class ExpectedGap(FrozenModel):
    fingerprint: str
    kind: GapKind
    critical: bool


class EvalExpectation(FrozenModel):
    expected_gaps: tuple[ExpectedGap, ...]
    forbidden_gap_fingerprints: tuple[str, ...] = ()


class PredictedGap(FrozenModel):
    fingerprint: str
    kind: GapKind


class EvalCost(FrozenModel):
    deterministic_jobs: int = 0
    cheap_model_jobs: int = 0
    standard_model_jobs: int = 0
    strong_model_jobs: int = 0
    frontier_model_jobs: int = 0
    human_escalations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    wall_clock_ms: int = 0


class EvalPrediction(FrozenModel):
    gaps: tuple[PredictedGap, ...]
    cost: EvalCost = EvalCost()


class EvalScore(FrozenModel):
    critical_gaps_detected: int
    critical_gaps_missed: int
    noncritical_gaps_detected: int
    noncritical_gaps_missed: int
    false_gaps: int
    precision: float
    recall: float
    cost: EvalCost
```

`score_prediction` uses exact fingerprint matching. Compute precision as true predictions divided by total predictions and recall as expected gaps detected divided by expected gaps; return `1.0` when both numerator and denominator are zero.

- [ ] **Step 4: Implement physically separate input/judge loaders**

`load_input(fixture_dir)` reads only `input.json`.

`load_judge(fixture_dir)` reads only `judge.json`.

No function used by future execution code may return both in a single object. This is the first enforcement of the sealed-judge boundary.

- [ ] **Step 5: Add the first greenfield sealed fixture**

`evals/fixtures/greenfield/payments_vague/input.json`:

```json
{
  "fixture_id": "greenfield-payments-vague-v1",
  "family": "greenfield",
  "project_id": "EVAL-GF-1",
  "events": [
    {
      "event_type": "USER_STATED_INTENT",
      "text": "Build a payment platform that never loses money and is very fast.",
      "actor_id": "OWNER"
    }
  ],
  "artifact_refs": []
}
```

`evals/fixtures/greenfield/payments_vague/judge.json` must contain these critical expected gap fingerprints:

```text
AMBIGUITY:never-loses-money
AMBIGUITY:very-fast
MISSING_INFORMATION:jurisdiction
MISSING_INFORMATION:currency-scope
MISSING_SUCCESS_METRIC:latency
MISSING_VERIFICATION_OBLIGATION:money-conservation
```

This fixture is not expected to pass end-to-end until model-driven intent ingestion exists; in this milestone it proves the judge can remain separate and stable before the executor exists.

- [ ] **Step 6: Add the first brownfield sealed fixture**

`evals/fixtures/brownfield/retry_conflict/input.json` describes two observed artifact claims, one indicating retry count 3 and the other retry count 5, both marked as evidence rather than canonical intent.

`judge.json` must require the critical fingerprint:

```text
CONTRADICTION:legacy-retry-count
```

and the critical fingerprint:

```text
MISSING_AUTHORITY:legacy-retry-count
```

This fixture encodes the brownfield law that conflicting implementation evidence does not automatically decide intended behavior.

- [ ] **Step 7: Run scorer tests and fixture-loader tests**

Add tests that verify:

- `load_input` does not expose judge expectations,
- `load_judge` does not expose raw executor-only event content,
- the greenfield fixture loads as family `greenfield`,
- the brownfield fixture loads as family `brownfield`,
- exact scoring is deterministic.

Run:

```bash
uv run pytest tests/unit/test_eval_scorer.py -v
uv run ruff check src/foundry/evaluation tests/unit/test_eval_scorer.py
uv run mypy src/foundry/evaluation
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/foundry/evaluation evals/fixtures tests/unit/test_eval_scorer.py
git commit -m "feat: add sealed Intent Engine evaluation harness"
```

---

### Task 8: Add a minimal CLI and prove event -> replay -> closure -> package end to end

**Files:**
- Create: `src/foundry/cli.py`
- Create: `tests/e2e/test_replay_to_package.py`
- Modify: `README.md` if present; otherwise create it.

**Interfaces:**
- Consumes: event store, replay, closure, package, and evaluation modules from Tasks 4-7.
- Produces: human-operable commands `foundry events replay`, `foundry intent closure`, and `foundry eval score`; one e2e proof that persisted events reconstruct the same closed intent package every time.

- [ ] **Step 1: Write the end-to-end test first**

The e2e test must use a real PostgreSQL testcontainer and perform this sequence:

1. append a canonical `Intent`, `Goal`, `Requirement`, `Metric`, and `VerificationObligation` as typed events,
2. make the requirement relate to the metric via `MEASURED_BY` and to the verification obligation via `VERIFIED_BY`,
3. load the stream,
4. replay to `IntentState`,
5. evaluate closure for scope `core`,
6. build the Canonical Intent Package,
7. load and replay again,
8. assert the second state and package exactly equal the first.

This proves the v0 invariant: current semantic state is reconstructable from immutable history.

- [ ] **Step 2: Verify failure**

```bash
uv run pytest tests/e2e/test_replay_to_package.py -v
```

Expected: FAIL until the CLI/database wiring and any missing integration helpers are completed.

- [ ] **Step 3: Implement the CLI without adding business logic**

Create a Typer app with three command groups:

```text
foundry events replay PROJECT_ID --database-url DATABASE_URL
foundry intent closure PROJECT_ID --scope SCOPE --database-url DATABASE_URL
foundry eval score PREDICTION_JSON JUDGE_JSON
```

Rules:

- CLI handlers only parse arguments, call application/domain functions, and serialize results.
- `events replay` prints `IntentState.model_dump_json(indent=2)`.
- `intent closure` prints `ClosureResult.model_dump_json(indent=2)` and exits code 2 when not closed.
- `eval score` loads `EvalPrediction` and `EvalExpectation`, calls `score_prediction`, and prints JSON.
- No model-provider imports are permitted in `cli.py`.

- [ ] **Step 4: Add the project README as a decision-first entry point**

Create `README.md` with these sections:

```text
# Foundry
## Thesis
## Current Milestone: Intent Engine v0
## Architecture Boundary
## Local Setup
## Verification Commands
## Repository Laws
## What Does Not Exist Yet
```

The thesis section must state: implementation artifacts are replaceable; decisions, constraints, contracts, evidence, authority, and verification obligations are the durable system asset.

The current milestone must explicitly say Foundry does not generate code yet; v0 is proving the deterministic substrate for machine-operable intent.

Local setup commands:

```bash
uv sync --all-groups
docker compose up -d postgres
uv run alembic upgrade head
uv run pytest
```

Verification commands:

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

- [ ] **Step 5: Run the complete v0 verification suite**

```bash
uv run pytest -v
uv run ruff check .
uv run mypy src
```

Expected: all PASS.

- [ ] **Step 6: Run an explicit deterministic replay check twice**

After loading an e2e test project stream, run:

```bash
uv run foundry events replay PROJ-E2E --database-url postgresql+psycopg://foundry:foundry@localhost:5432/foundry > /tmp/foundry-state-1.json
uv run foundry events replay PROJ-E2E --database-url postgresql+psycopg://foundry:foundry@localhost:5432/foundry > /tmp/foundry-state-2.json
diff /tmp/foundry-state-1.json /tmp/foundry-state-2.json
```

Expected: `diff` exits 0 with no output.

- [ ] **Step 7: Commit**

```bash
git add src/foundry/cli.py tests/e2e/test_replay_to_package.py README.md
git commit -m "feat: prove deterministic Intent Engine v0 substrate"
```

---

## Milestone Acceptance Gate

Do not add LLM ingestion, research workers, routing, or context compilation until all of the following are true:

- [ ] `uv run pytest -v` passes.
- [ ] `uv run ruff check .` passes.
- [ ] `uv run mypy src` passes.
- [ ] A PostgreSQL event stream can be replayed twice into byte-equivalent JSON state.
- [ ] The same event stream yields the same Canonical Intent Package twice.
- [ ] A stale expected event-stream sequence is rejected.
- [ ] Duplicate event IDs are rejected.
- [ ] Authority and confidence remain separate in serialized semantic objects.
- [ ] A blocking gap prevents intent closure.
- [ ] A known non-blocking low-risk unknown may coexist with closure.
- [ ] A material requirement cannot close without required metric/verification relations or explicit exemptions.
- [ ] The sealed evaluation loader keeps `input.json` and `judge.json` behind separate APIs.
- [ ] Both greenfield and brownfield fixtures use the same semantic and evaluation schemas.

## What the next plan may add only after this gate passes

The next implementation plan may introduce model-driven intent normalization, deterministic and model-based gap detectors, the Context Compiler, executor routing, research planning, evidence workers, and escalation rules. Those systems must consume this substrate rather than inventing parallel state or hidden model memory.
