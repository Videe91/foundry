# Foundry

Foundry is a software factory. It is not an AI software engineer.

**Code is an implementation artifact. Intent, decisions, constraints, evidence, authority, contracts, invariants, and verification obligations are the durable system asset.**

## Thesis

Implementation artifacts are replaceable. Decisions are durable.

Foundry preserves decisions and manufactures artifacts. A generated file, schema, prompt, or deployment manifest may change. The authorized intended state must remain reconstructable, evidence-backed, and verifiable.

## What Foundry Is

Foundry converts intent into verified running systems and keeps actual systems aligned with intended state.

The factory loop is:

```text
Intent → Architecture → Planning → Build → Verification
```

Models are compute, not project memory. Persistent state lives outside models. Material input enters canonical state only through typed events.

## Current Milestone: Intent Engine v0

Intent Engine v0 proves the **deterministic substrate** required for the future factory.

It can represent semantic intent, record immutable events, replay current state, represent gaps and jobs, evaluate Sufficient Intent Closure, project a Canonical Intent Package, persist an append-only PostgreSQL event ledger, and score sealed evaluation fixtures.

**Intent Engine v0 does not yet manufacture downstream production software.** It does not generate application code, choose full system architecture, ingest with models, compile worker context, route executors, run research workers, deploy infrastructure, or operate production systems.

## Deterministic Substrate

The proven loop is:

```text
typed intent events
        ↓
append-only PostgreSQL ledger
        ↓
ordered load
        ↓
deterministic replay
        ↓
IntentState
        ↓
Sufficient Intent Closure
        ↓
Canonical Intent Package
```

Current Intent State is a projection. Event history is the durable history. Replay of the same stream must produce byte-equivalent JSON state and the same Canonical Intent Package.

## Architecture Boundary

The Intent Engine owns **what must become true and why**. Downstream architecture owns **how**.

Python v0 is a modular monolith. There are no microservices, Kubernetes, graph databases, persistent super-agents, or model-provider couplings in this milestone.

`input.json` and `judge.json` are separate by architecture and loader API. v0 sealing is not an OS-level security boundary.

## Local Setup

```bash
uv sync --all-groups
docker compose up -d postgres
```

## Database Migration

The database must already be migrated before CLI replay or closure commands. The CLI does not auto-migrate.

```bash
uv run alembic upgrade head
```

Default Compose credentials:

```text
postgresql+psycopg://foundry:foundry@localhost:5432/foundry
```

## CLI

```bash
uv run foundry events replay PROJ-1 \
  --database-url postgresql+psycopg://foundry:foundry@localhost:5432/foundry

uv run foundry intent closure PROJ-1 \
  --scope core \
  --database-url postgresql+psycopg://foundry:foundry@localhost:5432/foundry

uv run foundry eval score prediction.json judge.json
```

`prediction.json` and `judge.json` are judge-side scorer inputs. The executor-facing path uses `input.json` only and must not load `judge.json`.

`intent closure` prints a `ClosureResult` and exits `2` when the requested scope is not closed.

## Tests

```bash
uv run pytest -v
uv run ruff check .
uv run mypy src
```

## Sealed Evaluation Fixtures

Fixtures live under `evals/fixtures/`.

- `greenfield/payments_vague` — messy stated intent with expected critical gaps
- `brownfield/retry_conflict` — conflicting observed claims that must not become canonical intent

Load execution input with `load_input`. Load the answer key with `load_judge`. There is no combined loader.

## What v0 Does Not Yet Do

v0 does not yet:

- generate downstream production application/system code
- ingest intent with models
- compile advanced worker context
- route executors
- run research workers
- select full system architecture
- deploy infrastructure
- operate production systems
- train ML models
- provide a graphical IDE
