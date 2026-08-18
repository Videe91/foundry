# Foundry Rulings Ledger

Cortex rulings on floor-flagged issues. A ruling recorded here is settled law:
the floor must not re-flag it, and future packets inherit it. Format: packet
the flag came from, the issue, the ruling, and where it takes effect.

## R-001 — Empty-string defaults in CallTags (from P-001, note 1)

**Ruling: RATIFIED.** The gate must be the single voice of rejection, so core
tags default to `""` and the gate treats empty-or-whitespace as missing;
`department` is a validated `str`, not an Enum. Settled pattern for all future
gate-style validation: our error type speaks, never a construction-time error.

## R-002 — Payload placeholder `prompt` (from P-001, note 2)

**Ruling: ACCEPTED for P-001, SUPERSEDED by P-002.** Payload is
`messages: list[Message]`, min length 1. `prompt` is retired. Closed.

## R-003 — Missing [build-system] (from P-001, note 3)

**Ruling: ACCEPTED — packet defect, fixed in P-002.** `hatchling==1.32.0`
pinned as the build backend. Standing rule for packet authors: a build backend
is a dependency and must be pinned like one.

## R-004 — Header + "create exactly this" (from P-002, note 1)

**Ruling: RATIFIED as precedent.** When a packet says "create exactly this"
and Law rule 7 requires a header: header above, packet block verbatim beneath.
Both laws satisfied, neither altered. Applies to all future literal-content
files.

## R-005 — ModelRegistry.resolve (from P-002, note 2)

**Ruling: RATIFIED, Dictionary amended.** Role resolution lives on the
registry as `ModelRegistry.resolve(role)`. Official Dictionary name as of
P-003.

## R-006 — ProviderCallError location (from P-002, note 3)

**Ruling: RATIFIED. SETTLED — do not re-flag.** `ProviderCallError` lives in
`router.py`: it is a routing failure, not a registry failure. Standing rule
for packet authors: every Dictionary name gets an explicit file assignment.

## R-007 — Wheel-packages line + version 0.2.0 (from P-002, note 4)

**Ruling: RATIFIED.** Both were mechanical consequences of stated
instructions (installability; header versions). Mechanical consequences of
explicit instructions are within floor scope.

## R-008 — Module-level litellm import (from P-002 review, floor judgment call)

**Ruling: S1, FIXED in P-003.** Lazy imports inside the None-branches;
module-level litellm import is forbidden and test-enforced. Measured effect:
suite 6.81s → 0.18s. Closed.

## R-009 — test_router.py at 294/300 lines (from P-003)

**Ruling: S1, DEFERRED with a standing authorization.** The floor's
restructure-within-scope was correct and is ratified. The next packet that
touches the Switchboard test suite is pre-authorized to create
`switchboard/tests/conftest.py` and move the shared fakes there. Until such a
packet exists, no action.

## R-010 — pyproject version drift 0.2.0 vs 0.3.0 (from P-003, note 2)

**Ruling: ACCEPTED, DEFERRED.** Scope rules outrank header consistency — the
floor's priority order was correct. The next packet listing pyproject.toml as
modifiable bumps the version to match its wave. Until then, drift is known and
tolerated.

## R-011 — Branch chain (from P-003, note 3)

**Ruling: RATIFIED.** Building P-003 on the P-002 branch was correct — main
lacked P-002, and recreating stamped files is forbidden. Merge order: P-002
PR into main first, then P-003, so each PR shows only its own wave's diff.

## R-012 — registry.toml is configuration, not law (from P-004, registry section)

**Ruling: RATIFIED as a standing rule.** `registry.toml` is **user
configuration**. The human may edit role→model assignments at any time with no
packet, no build, and no stamp — that is the file's entire purpose. Code must
never hardcode a model string; it only reads the registry. Packets after P-004
must not prescribe role→model choices; a future settings layer will manage this
file. Roles may exist in the registry before any code uses them: presence in
config is cheap, and it proves the wiring before the need arrives.

**Corollary the floor is required to flag (see T-001):** if the registry is
configuration, then no stamped test may assert on its *values*. Tests may
assert structure and behaviour only. `test_registry.py` currently violates this
and is stamped, so P-004's registry replacement could not be executed.

## R-013 — Keys exist only at the Switchboard (from P-004, amendment)

**Ruling: RATIFIED as a standing rule.** Keys exist only at the Switchboard —
no other component may ever read provider keys, load `.env`, or accept keys as
parameters; the Switchboard is the single door to all providers.

**Where it takes effect:** `.env` and `.env.example` live at the project root
and `.env` is gitignored. `load_env()` lives in `smoke.py` and is called only
from its main path. Library code under `src/` must never import dotenv or read
the environment — provider credentials reach the provider through LiteLLM's own
env lookup and through nothing Foundry writes. Verification should treat any
`src/` reference to a key name, `os.environ`, or dotenv as a violation of this
ruling regardless of whether the feature works.

## R-014 — Tests on configuration assert structure, never values (from T-001)

**Ruling: RATIFIED.** Tests on configuration files assert STRUCTURE, never
VALUES. Config belongs to the human (R-012); a test that pins config values
contradicts that ownership. `test_registry.py` unstamped for this packet only,
then re-stamped.

**Where it takes effect:** `test_registry.py` now asserts that the shipped
`registry.toml` parses, that every entry has a non-empty `model`, a list of
non-empty string `fallbacks`, and a positive integer `max_tokens`, and that a
`default` role exists. All resolution behaviour is proven against synthetic
TOML written to `tmp_path`, so the real file's values are never load-bearing.
Verified empirically: swapping `architect` to a different model, changing its
ceiling, and adding a cross-family fallback leaves the suite green.

**Standing rule for packet authors:** any future test that reads a
user-editable config file inherits this. Assert the shape; never the contents.

## R-006 corollary — Attachment and PingResult (from P-004, notes 1 and 2)

**Ruling: BOTH RATIFIED, Dictionary amended.**

`Attachment` is assigned to `request.py`. The floor's reasoning is accepted:
`SwitchboardRequest.attachments` needs the type, and placing it in
`adapters.py` would create an import cycle, since `adapters.py` imports
`Message` from `request.py`. The import-cycle constraint decides the
assignment.

`PingResult` is ratified into the Dictionary as the smoke script's per-model
reachability result (fields: `model: str`, `ok: bool`, `seconds: float`,
`error: str | None`), living in `smoke.py`. Standing reminder under R-006: a
packet that introduces a return shape must name it and assign it a file.

## R-015 — Solo flow (from P-004, flag 1)

**Ruling: RATIFIED as the new normal.** Solo flow — pushes to main are
permitted; nothing builds on top of a push until Cortex's cold verification
stamps it. The stamp is the review. Branch/PR flow returns if contributors
multiply.

**Reasoning of record:** the review that actually protects the codebase is
Cortex's cold verification from a fresh clone, which happens after any push,
branch or main, identically. PR ceremony added steps without adding protection
while no second human reviews diffs. The law updates to match reality; the gate
is verification, not branching. Revisitable as a config-of-process.
`2321f0d` is stamped.

## R-016 — Necessary stamped-file modification (from P-004, flag 2)

**Ruling: RATIFIED.** An explicit packet-author instruction that necessarily
touches stamped files is a one-amendment unstamping of exactly those files;
they re-stamp on the next cold-verified green build. `registry.py` and
`test_registry.py` re-stamped as of P-004 completion.

**Standing pattern for the floor:** execute the explicit instruction, then flag
the implicit unstamping upward. That handling is correct and is now the
expected behaviour. Parallel to R-014.

## R-017 — tests/test_effort.py (from P-004, flag 3)

**Ruling: RATIFIED on the R-009 precedent.** `tests/test_effort.py` ratified
into the file map per the R-009 precedent — topic splits beat repeated
compaction.

**Reasoning of record:** R-009's whole point was that `test_router.py` needed
structural relief, and a topic-focused test file is cleaner than a
shared-fixture squeeze.

## R-018 — File map, test_cache.py pre-authorization, include_usage (from P-005)

**Ruling: RATIFIED.** `smoke_debug.py` and `smoke_fixtures.py` ratified into the
file map (R-017 precedent).

**Pre-authorization:** the next packet touching the Switchboard test suite
creates `tests/test_cache.py` and moves cache-extraction tests there.

**Conditional pre-authorization:** if streaming reports zero tokens on a live
run, adding `stream_options` `include_usage` to the streaming path is a
one-line authorized amendment, logged, no new packet.

**Notes of record:** topic splits beat compaction — diagnostics and fixture
bytes are exactly the right things to live apart from the main script. Keeping
`dump_usage` in `smoke.py` per its Dictionary assignment was the correct
precedence read. The `test_cache.py` authorization takes the same
standing-authorization shape as R-009. If a live run reports tokens correctly,
the conditional authorization expires unused.
