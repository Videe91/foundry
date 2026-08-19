# Packet P-011 — The Workspace: A Project Is a Folder With a Constitution

**Department:** Coding Floor
**Wave:** 10 (first post-Switchboard component; design doc v2.2 Section 16 is the authority)
**Language:** Python 3.12

**Architecture context:** Every department works INSIDE a project; the Workspace is where a project physically lives. It is deliberately dumb — pure structure, zero AI, the Conductor philosophy: create the skeleton, validate it, hand out typed paths. No department ever computes a path; it asks the Workspace. This packet builds the module and wires the meter's project_id tag to a real destination.

## One job

A `workspace` package: `create_project(slug)` stamps the standard skeleton under the workspace root; `open_project(slug_or_path)` validates and returns a typed handle exposing every standard path; registry layering (project registry over global); lifecycle state read/write with only the first transition enforced; and the git law (projects/ gitignored) applied in the same commit.

## Dictionary

| Concept | Name |
|---|---|
| The package | `workspace` (new top-level: `workspace/src/workspace/`, its own pyproject, same pins discipline) |
| Create | `create_project(slug: str, name: str, root: Path \| None = None) -> Project` |
| Open | `open_project(slug_or_path: str \| Path, root: Path \| None = None) -> Project` |
| The handle | `Project` (frozen-ish model: `slug`, `name`, `root_dir`, `status`, plus typed path properties below) |
| Path properties | `intent_dir`, `architecture_dir`, `dictionary_path`, `packets_dir`, `registry_path`, `ledger_dir`, `build_log_path`, `rulings_path`, `tickets_dir`, `meter_path`, `evidence_path`, `state_dir`, `src_dir`, `project_toml_path` |
| Birth certificate | `project.toml` (keys: `id` — uuid4 str, `slug`, `name`, `created` — UTC ISO, `status`, `signatures` — table, empty at birth) |
| Lifecycle states | `draft`, `intent_signed`, `building`, `adversarial`, `deployed`, `live`, `amended` (a `Status` enum-like validated str) |
| State change | `Project.advance(to: str, signature: str) -> None` |
| Registry resolution | `Project.effective_registry_path() -> Path` — project's registry.toml if present, else the global |
| Workspace root | env `FOUNDRY_WORKSPACE_ROOT`; default `<repo-root>/projects/` |
| Invalid workspace | `WorkspaceError` (naming what is missing or malformed) |

## Files to create or modify (each under 300 lines)

```
(project root)/.gitignore    — MODIFY: add projects/ (the git law, same commit)
workspace/
├── pyproject.toml           — NEW: pins pydantic==2.11.7, pytest==8.4.1, hatchling==1.32.0 (dev), version 0.1.0
├── src/workspace/
│   ├── __init__.py          — exports create_project, open_project, Project, WorkspaceError
│   ├── skeleton.py          — the directory layout, one place, as data not code paths
│   ├── project.py           — Project model, path properties, advance, effective_registry_path
│   └── factory.py           — create_project / open_project
└── tests/
    ├── test_create.py
    ├── test_open.py
    └── test_lifecycle.py
```

The Switchboard is untouched in this packet — wiring the meter into project ledgers is P-012's job (one integration at a time; the Workspace must exist before anything can point at it).

## Behaviour contract

1. **create_project:** slug must be lowercase kebab (`[a-z0-9][a-z0-9-]*`) — anything else `ValueError` naming the offense; refuses to create over an existing directory (`WorkspaceError`); stamps every directory in the skeleton with a `.gitkeep` where empty; writes project.toml with status `draft`, a fresh uuid4, UTC created; writes ledger/build-log.md with a one-line birth entry; does NOT create a project registry.toml (absence = inherit global, by design).
2. **open_project:** validates the skeleton — every required directory and project.toml present and parseable; anything missing → `WorkspaceError` naming exactly what. Never repairs silently (a broken workspace is a finding, not a fix-up).
3. **Root resolution:** explicit `root` arg > `FOUNDRY_WORKSPACE_ROOT` env > default `projects/` under the repo root. The default is computed relative to the workspace package's installation location's repo — if that cannot be determined confidently, require the env var and say so (`WorkspaceError`), never guess into a random directory. R-013 analogue: workspace code reads only this one env var, nothing else.
4. **Lifecycle:** `advance(to, signature)` permits only forward transitions in the declared order (plus `live → amended → building` for the long-haul loop, per design doc Section 13); each advance appends `{status, at, signature}` to the signatures table and rewrites project.toml atomically (write temp, rename). ONLY `draft → intent_signed` is gate-checked today (requires a non-empty signature string); all other transitions validate order but no department gates — enforcement is added as departments are built (design doc 16.2 rule 4). Invalid transition → `WorkspaceError` naming from/to.
5. **effective_registry_path:** project registry.toml if the file exists, else the global switchboard registry path (passed in or discovered via the same root logic — keep it a parameter with a sensible default rather than a hard import of switchboard; the Workspace must not depend on the Switchboard).
6. **Dumbness clause:** no LLM calls, no litellm import, no network, no reading of any env var beyond FOUNDRY_WORKSPACE_ROOT. A test asserts litellm is not imported by the workspace package (the R-008/P-003 subprocess pattern).
7. **The git law:** `projects/` added to the root .gitignore in this same commit; a test-adjacent check (or documented manual verification in the build log) that `git check-ignore projects/anything` resolves.

## Tests that must pass (ALL offline, all against tmp_path roots)

test_create.py:
- creates the full skeleton — every Dictionary path property exists on disk after create
- project.toml round-trips: id is uuid4-shaped, created parses as UTC ISO, status == "draft", signatures empty
- bad slugs rejected naming the offense: "MyApp", "my_app", "-x", "" (parametrized)
- creating over an existing directory → WorkspaceError
- empty dirs carry .gitkeep

test_open.py:
- open after create returns equal paths (create → open → same Project surface)
- each required piece removed (parametrized: project.toml, ledger/, packets/, state/) → WorkspaceError naming exactly the missing piece
- malformed project.toml (bad TOML, missing keys) → WorkspaceError naming the key
- root resolution order: explicit arg beats env beats default (env monkeypatched)
- effective_registry_path: absent project registry → the provided global; present → the project's own

test_lifecycle.py:
- draft → intent_signed with a signature: status advances, signatures table gains the entry, file rewritten atomically (old content never half-written — assert via read-back)
- draft → intent_signed with empty signature → WorkspaceError
- skipping states (draft → building) → WorkspaceError naming from/to
- the long-haul loop: live → amended → building permitted; amended → deployed not
- workspace package imports no litellm (subprocess assertion)

Full suite green (Switchboard's 332 + these — run everything).

## Forbidden

- No Switchboard imports, no litellm, no network, no AI anywhere in the package.
- No silent repair in open_project; no path computation outside skeleton.py.
- No department gates beyond draft → intent_signed (they arrive with their departments).
- No registry content decisions (R-012 — layering resolves WHICH file, never what is in it).
- No new dependencies beyond the pinned three.
