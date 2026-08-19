# Packet P-012 — The Meter Learns Addresses: Receipts Land in Project Ledgers

**Department:** Coding Floor
**Wave:** 11 (builds on P-011; Switchboard 340 + Workspace 73, both stamped)
**Language:** Python 3.12

**Architecture context:** Since P-001 every call has carried a mandatory `project_id` tag pointing at nothing. Since P-011 projects physically exist, each with its own `ledger/meter.jsonl`. This packet connects them — with the seam kept clean: **the Switchboard never learns what a project is.** It continues to write receipts wherever its `MeterLedger.path` points. The Workspace, which owns the concept of a project, provides the resolution from project_id to that project's meter path. The two packages meet only through a path — the same discipline as `effective_registry_path` (a parameter, not an import), asserted by the existing subprocess guards which must stay green.

## One job

A caller who knows a project can obtain that project's meter — `Project.meter()` — and a caller holding several projects can route per-call receipts to the right ledger with a small resolver, without the Switchboard changing at all. Plus the smoke script demonstrates it end to end.

## Dictionary

| Concept | Name |
|---|---|
| Project meter accessor | `Project.meter() -> MeterLedger`-shaped object (see contract 1 for the typing seam) |
| The router | `MeterRouter` (file: `workspace/src/workspace/meter_router.py`) |
| Its constructor | `MeterRouter(resolve: Callable[[str], Path])` — maps a project_id (or slug) to a meter path |
| Its record method | `MeterRouter.record(record) -> None` — reads `record.tags.project_id`, resolves, appends to that path |
| Unresolvable id handling | falls back to a `default_path` given at construction (`MeterRouter(resolve, default_path=...)`); no default → the record is dropped with a `RuntimeWarning` naming the id — never an exception (the meter must not kill calls, P-003 law) |
| Convenience resolver | `workspace_resolver(root: Path) -> Callable[[str], Path]` — resolves a slug to `<root>/<slug>/ledger/meter.jsonl` for projects that exist; raises `KeyError` inside for unknown slugs (the router catches it and applies fallback) |

## Files to create or modify (each under 300 lines)

```
workspace/
├── src/workspace/
│   ├── __init__.py        — MODIFY: export MeterRouter, workspace_resolver
│   ├── project.py         — MODIFY: add Project.meter()
│   └── meter_router.py    — NEW
└── tests/
    └── test_meter_router.py — NEW

switchboard/
└── smoke.py / smoke_proves.py — MODIFY (per R-026 responsibility inheritance): the
    end-to-end demonstration, contract 5
```

**The Switchboard's src/ is untouched.** If anything appears to require changing it, STOP and ticket — that would mean the seam is wrong, and the seam is the point.

## Behaviour contract

1. **The typing seam:** the Workspace must not import the Switchboard (the P-011 subprocess guard stays green). `Project.meter()` and `MeterRouter` therefore construct/accept the meter by *shape*, not by import: `Project.meter()` returns an object with `.path` and `.record(...)` — implemented by constructing the Switchboard's `MeterLedger` ONLY if the caller passes the class in (`Project.meter(ledger_cls)`), OR by a minimal internal append-only JSONL writer with the identical two-member surface (choose the internal writer; it is ~15 lines, keeps the package dependency-free, and the JSONL format is pinned by P-003's tests on the other side — add one round-trip test here proving a record written by the internal writer parses identically to a Switchboard-written one, using a captured real line as the fixture, R-019 style).
2. **MeterRouter.record:** extract `tags.project_id` (attribute or mapping access — accept both shapes, tested); resolve; append. Resolution failure → default_path if given, else drop-with-warning naming the id. A resolver that *raises* is treated as resolution failure (caught), never propagated — same containment as P-003 contract 6.
3. **Multi-project isolation:** two records with different project_ids land in two different files; neither file contains the other's record (tested with two tmp projects).
4. **workspace_resolver:** slug must correspond to an existing, valid project directory under root (cheap existence check of `<root>/<slug>/ledger/`, not a full open_project — the router is hot-path adjacent and must stay dumb-fast); missing → KeyError inside, router fallback applies.
5. **Smoke demonstration (the live proof, human-run):** smoke gains a `--project <slug>` option: when given, smoke creates the project under the workspace root if absent (via create_project), and every prove-phase meter write routes through a MeterRouter into that project's ledger instead of the global `ledger/meter.jsonl`. Output ends with: "Receipts appended to <project>/ledger/meter.jsonl (N records)". Without the flag: behavior byte-identical to today (tested: no flag → global path used, project machinery never invoked).
6. **No double-writing:** a routed record lands in exactly one file — project ledger when routed, global when not. Never both.

## Tests that must pass (ALL offline)

test_meter_router.py:
- record with a resolvable project_id → appended to that project's meter path, one line, parseable
- two projects, two records → correct isolation (contract 3)
- unresolvable id + default_path → lands in default; without default → dropped with RuntimeWarning naming the id; a raising resolver → same fallback path, exception contained
- tags as attribute-object and as mapping both work
- round-trip fixture: internal writer's line parses identically to a captured real Switchboard meter line (fixture cited)
- Project.meter().record(...) appends to that project's meter_path

Workspace guards (existing, must stay green): importing workspace pulls in neither litellm nor switchboard.

smoke tests (topic-correct homes per R-023/R-026):
- --project flag: meter writes route to the project ledger (fakes); no flag → global path, create_project never called
- the flag creates the project when absent, reuses when present (no WorkspaceError on second run)

Full suite green — Switchboard 340 + Workspace 73 + new.

## Forbidden

- No Switchboard src/ changes (STOP-and-ticket if seemingly needed).
- No workspace import of switchboard or litellm (guards enforce).
- No new dependencies, no keys, no network in tests; only the human runs smoke.
- No batching, buffering, or async in the router — append-per-record, same as P-003.
- No project lifecycle changes; --project does not sign or advance anything.
