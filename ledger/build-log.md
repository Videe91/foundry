# Foundry Build Log

## P-001 — Switchboard Scaffold — 2026-08-18

**Built:** The `switchboard/` package skeleton and the mandatory tag gate.
Seven files, exactly as listed in the packet: `pyproject.toml`,
`src/switchboard/{__init__,tags,request,router}.py`, and
`tests/{test_tags,test_router}.py`. `route_call` validates `CallTags` and
returns a `SwitchboardResponse` with `status="stub"`, the echoed tags, and a
UTC `received_at`. No LiteLLM, no HTTP, no network, no config or env reading.

**Dependencies:** `pydantic==2.11.7` and `pytest==8.4.1` only, exactly as
pinned. Nothing else installed or imported; standard library otherwise.

**Tests:** 14 passed, 0 failed (pytest 8.4.1, Python 3.12.11, pydantic 2.11.7).
All six behaviours the packet requires are covered — valid tags echo back with
status "stub"; missing `project_id`; missing `role`; invalid department
"marketing"; extra unknown field rejected; optional fields omissible — each
tested at the `validate_tags` unit level and through `route_call`.

**Deviations:** None.

**Notes for the packet author** (no decision taken on the floor, flagging only):

1. The packet requires `MissingTagsError` naming a missing `project_id` or
   `role`. That means `CallTags` cannot declare those fields as
   pydantic-required, or construction would fail with `ValidationError` before
   the gate ever runs. They are declared with an empty-string default and the
   gate treats empty-or-whitespace as missing. Same reason `department` is a
   validated `str` rather than an `Enum`: contract line 3 requires
   `MissingTagsError` naming the invalid value, not a pydantic error.
2. `SwitchboardRequest` needs a payload field alongside `tags`; the packet's
   dictionary does not name one. Built as `prompt: str` defaulting to `""` so
   the tags remain the only gate in this packet. Confirm the intended shape
   before P-002 adds real calls.
3. `pyproject.toml` declares no `[build-system]`. Every backend would mean an
   unlisted package or a floating range, both forbidden by rule 4. The package
   is therefore not `pip install`-able yet; tests run via the `pythonpath`
   setting. Pin a backend in a future packet if installability is wanted.

## P-002 — Switchboard Routing: LiteLLM + Model Registry — 2026-08-18

**Built:** Role-based routing behind the P-001 tag gate. New `registry.toml`
and `registry.py` (`RoleRoute`, `ModelRegistry`, `load_registry`,
`UnknownRoleError`); `router.py` now resolves the caller's role to a model,
calls it through `completion_fn` (defaulting to `litellm.completion`), walks
the fallback chain on any exception, and raises `ProviderCallError` when every
model is exhausted. `request.py` replaces `prompt` with
`messages: list[Message]` (min length 1) and adds `model_used` / `content` to
`SwitchboardResponse`; `status` is now `"ok"` and `"stub"` is fully retired.
`__init__.py` additionally exports `load_registry`, `Message`,
`UnknownRoleError`, and `ProviderCallError`.

**Cortex rulings applied:** Ticket 2 — `prompt` removed entirely, replaced by
`messages`. Ticket 3 — `pyproject.toml` gained `[build-system]` with
`hatchling==1.32.0`; `pip install -e .` verified working (`Successfully
installed switchboard-0.2.0`, importable from the source tree).

**Stamped files:** `tags.py` and `test_tags.py` were NOT modified. Verified by
`git diff --stat` against the P-001 commit — empty.

**Dependencies:** `pydantic==2.11.7`, `litellm==1.97.0`, `pytest==8.4.1`,
`hatchling==1.32.0` — exact pins, all four co-resolved without moving any
version. Registry parsed with stdlib `tomllib`; no extra parser. No key
handling code anywhere; scan for key/secret/token patterns came back clean.

**Tests:** 26 passed, 0 failed (pytest 8.4.1, Python 3.12.11, pydantic 2.11.7,
litellm 1.97.0). 7 in `test_registry.py`, 11 in `test_router.py`, 8 unchanged
in `test_tags.py`. Every behaviour the packet lists is covered, including
fallback promotion, `ProviderCallError` naming all three models tried, the
gate firing before any provider call (fake call count asserted 0), plain-dict
message conversion with the role's `max_tokens`, and empty-messages rejection.
Fully offline — the fake `completion_fn` is a plain class in the test file, no
mocking library, no network, no keys. All files under 300 lines (largest:
`test_router.py` at 197).

**Deviations:** None.

**Notes for the packet author** (no decision taken on the floor, flagging only):

1. `registry.toml` was specified as "create exactly this", but Law rule 7
   requires every file to open with a packet/job/version header. Resolved by
   placing the three-line header above the packet's block, which is reproduced
   verbatim and unaltered beneath it. Confirm this is the intended reading.
2. The Dictionary names no method for role resolution, yet `test_registry.py`
   owns the resolution tests — so it lives on the registry as
   `ModelRegistry.resolve(role)`. Add it to the Dictionary if that name should
   be fixed.
3. `ProviderCallError` is named in the Dictionary but assigned to no file; the
   file list gives `registry.py` only the registry names, so it sits in
   `router.py` by elimination.
4. `[tool.hatch.build.targets.wheel] packages = ["src/switchboard"]` was added
   so the backend finds the src layout, and the project version moved 0.1.0 →
   0.2.0 to match the file headers. Both sit inside the packet's "MODIFY
   pyproject.toml" scope but were not spelled out.

## P-003 — Switchboard Meter: Tokens and Cost per Tagged Call — 2026-08-18

**Built:** Metering for every successful routed call. New `meter.py` (`Usage`
with `ge=0` token counts, `MeterRecord`, `MeterLedger` appending one JSON line
per record and creating parent directories). `router.py` gained `cost_fn` and
`meter` parameters, usage extraction from the provider response, best-effort
cost, and a meter hook that fires after the response is fully built.
`request.py` adds `usage: Usage` to `SwitchboardResponse`; `__init__.py`
additionally exports `Usage`, `MeterRecord`, `MeterLedger`.

**Cortex ruling applied (S1 lazy import):** `litellm` is no longer imported at
module level. Both uses are function-local — `litellm.completion` inside
`route_call`'s `completion_fn is None` branch, and `litellm.completion_cost`
inside the cost helper's. Measured effect: the full suite went from 6.81s
(P-002) to 0.18s, a ~38x speedup. A subprocess test asserts `litellm` is
absent from `sys.modules` after importing `switchboard.router`.

**Failure isolation (contracts 2, 3, 6):** the meter cannot kill a call.
Missing/unusable `usage` records 0/0/0; a cost function that raises or returns
a non-number yields `cost_usd=None`; a `record()` that raises is converted to a
`RuntimeWarning` and the response is still returned. Per contract 8, failed
calls (all fallbacks exhausted) are not metered, and that scope boundary is
stated in `meter.py`'s header.

**Stamped files:** `tags.py`, `test_tags.py`, `registry.py`,
`test_registry.py`, `registry.toml` were NOT modified — verified by
`git diff --stat`, empty for all five. `pyproject.toml` was also left untouched
as it is not in this packet's declared scope.

**Dependencies:** none added. Only `json`, `os`, `subprocess`, `sys`,
`pathlib`, `datetime`, `types`, `warnings`, `collections.abc` from the standard
library, plus the existing `pydantic` pin.

**Tests:** 41 passed, 0 failed (pytest 8.4.1, Python 3.12.11, pydantic 2.11.7).
7 in `test_meter.py`, 19 in `test_router.py` (17 functions, one parametrized
into 3 cases), 7 in `test_registry.py`, 8 in `test_tags.py`. Every behaviour
the packet lists is covered. Fully offline — no network, no keys, stdlib fakes
only.

**Deviations:** None.

**Constraint hit — Law rule 3 (300-line ceiling):** `test_router.py` first came
in at 373 lines carrying the P-002 suite plus the seven new behaviours. Rather
than report the packet as wrong, the file was restructured to 294 lines with no
loss of coverage: the three tag-gate tests became one `parametrize` with three
cases, the three fake response classes collapsed into stdlib `SimpleNamespace`,
and intra-test blank lines were removed. Flagging because the headroom is now
6 lines — **the next packet that adds a test to `test_router.py` will breach
the ceiling.** That file needs a split, or the packet needs to authorize a
`conftest.py` for the shared fakes.

**Notes for the packet author** (no decision taken on the floor, flagging only):

1. `ProviderCallError` remains in `router.py` (P-002 note 3, still unratified).
2. `pyproject.toml` still declares version 0.2.0 while the P-003 file headers
   say 0.3.0, because the packet does not list `pyproject.toml` as modifiable
   and scope rules outrank header consistency. Add it to a future packet's file
   list if the package version should track the wave.
3. P-003 was built on the `p-002-switchboard-routing` branch, not on `main` —
   `main` does not contain P-002, so building there would have required
   recreating stamped files.

## P-004 — Family One: Anthropic Adapter — 2026-08-18

**Supersession:** P-004 (Anthropic Adapter) supersedes the earlier P-004
"First Light" packet. The packet instructs deleting
`packets/P-004-first-light.md`. **That file does not exist and never has** —
not in the working tree, not on any branch, not anywhere in git history
(`git log --all --diff-filter=A -- packets/` shows only P-001, P-002, P-003).
Nothing was deleted. The supersession is recorded here as instructed; the
delete was a no-op with no target.

**Built:** The family-adapter pattern and its Anthropic implementation.
New `adapters.py` (`FamilyAdapter` protocol, `AnthropicAdapter`, `adapter_for`)
marks the system block as an ephemeral cache breakpoint and inlines
base64 image/PDF attachments onto the last user message. `request.py` gains
`Attachment`, `system`, and `attachments`; `meter.py`'s `Usage` gains
`cached_tokens` and `cache_creation_tokens`; `router.py` selects an adapter per
attempt and extracts the cache counters. New `smoke.py` (ping phase + three
prove phases), new `tests/conftest.py`, `test_adapters.py`, `test_smoke.py`.
`pyproject.toml` → 0.4.0 with a `smoke` extra.

**Amendment 1 applied:** `.env.example` and `.env` live at the PROJECT ROOT,
not in `switchboard/`. `.env` is in the root `.gitignore` — verified with
`git check-ignore`, which resolves it to `.gitignore:2:.env`. `load_env()` uses
`find_dotenv()`, which walks up from `smoke.py` and therefore finds the root
`.env` from any working directory.

**Amendment 2 applied:** R-012 and R-013 appended to `ledger/rulings.md`.

**Cortex rulings applied:** R-009 — `tests/conftest.py` created and the shared
fakes moved there; `test_router.py` is 278 lines with four new tests added, down
from a projected breach. R-010 — `pyproject.toml` version is now 0.4.0, closing
the drift.

**Dependencies:** `python-dotenv==1.2.3` added to the `smoke` extra only, and
verified to resolve without disturbing `pydantic==2.11.7`, `litellm==1.97.0`,
`pytest==8.4.1`. No other additions. dotenv is imported *inside* `load_env()`,
so the offline suite never loads it and `src/` never references it.

**Stamped files:** `tags.py`, `test_tags.py`, `registry.py`, `test_registry.py`,
`test_meter.py` — all five verified unchanged by `git diff --stat`. The
packet's prediction held: `test_meter.py` still passes untouched, because the
two new `Usage` fields default to 0.

**Tests:** 63 passed, 0 failed (pytest 8.4.1, Python 3.12.11, pydantic 2.11.7),
in 0.12s. 10 adapters, 24 router, 7 smoke, 7 meter, 7 registry, 8 tags. Fully
offline: no network, no keys, no dotenv. `smoke.py` was NOT run — the human
runs it. Every file under 300 lines (largest: `test_router.py` at 278).

**DEVIATION — one item of the packet was NOT built.** `registry.toml` was not
replaced. P-004 orders it REPLACED while also declaring `test_registry.py`
FORBIDDEN to change and requiring a green suite; those three cannot hold at
once, because the stamped test asserts on the registry's *values*. Demonstrated
empirically and then reverted:

```
FAILED test_registry_file_parses_and_architect_resolves  (opus-5 vs sonnet-4-6)
FAILED test_every_declared_role_is_present               (architect_max is new)
FAILED test_unknown_role_resolves_to_default_entry       (assert 64000 == 1024)
3 failed, 4 passed
```

Editing a stamped test is forbidden; keeping a red suite is forbidden. Filed as
`ledger/tickets/T-001-registry-replace-vs-stamped-test.md` with a recommended
ruling: unstamp `test_registry.py` for one packet and rewrite it to assert
structure, not values — which is what R-012 requires anyway. **The Anthropic
registry block is therefore not yet in place, so `smoke.py` would currently
ping the old P-002 model strings. Do not run it until T-001 is ruled on.**

**Notes for the packet author** (no decision taken on the floor, flagging only):

1. `Attachment` has no file assignment in the Dictionary (R-006 requires one).
   It is in `request.py`, because `SwitchboardRequest.attachments` needs it and
   putting it in `adapters.py` would create an import cycle with `request.py`.
2. `PingResult` is a name the floor had to invent — the smoke phases need a
   return type and the Dictionary names none. Ratify or rename.
3. Attachments with no user message to carry them raise `ValueError`. The
   packet says attachments ride "the LAST user message" but does not say what
   happens when there is none; silently attaching them to an assistant message
   would produce a payload providers reject.
4. `pythonpath` in `pyproject.toml` gained `"."` so `test_smoke.py` can import
   `smoke`. Mechanical consequence of the packet requiring smoke tests
   (R-007 precedent).
5. The ~1,500-word cache block is one fixed paragraph repeated 30 times
   (1,560 words), rather than 1,500 words of unique prose, which would have
   pushed `smoke.py` past the 300-line ceiling. It is identical across calls by
   construction, which is what caching requires.

## P-004 amendment — T-001 fix (R-014) — 2026-08-18

**Built:** The T-001 resolution, executed as an amendment to P-004. This closes
the one item the original P-004 build could not deliver.

1. **`test_registry.py` rewritten (unstamped for this packet only, per R-014).**
   It now asserts STRUCTURE, never VALUES. Against the shipped file: the roles
   table parses; every entry has a non-empty `str` `model`, a `list` of
   non-empty `str` `fallbacks`, and an `int` `max_tokens > 0`; a `default` role
   exists. All resolution behaviour — known role resolves to its own entry,
   unknown role falls through to `default`, a registry with no `default` raises
   `UnknownRoleError` naming the role, a missing `model` or non-list
   `fallbacks` raises `ValueError` naming the role, a missing file raises
   `FileNotFoundError` — is proven against synthetic TOML written to
   `tmp_path`. The real `registry.toml` is never load-bearing for behaviour.

2. **`registry.toml` REPLACED** with the P-004 Anthropic block: `architect` →
   opus-5, the `architect_max` escalation tier → fable-5, `judge` → sonnet-5,
   `floor_agent` and `default` → haiku-4-5, with 128k/64k ceilings. Verified
   byte-for-byte against the packet's block by extracting the fenced TOML from
   the packet and diffing (`IDENTICAL`), with the R-004 header above it.

3. **Rulings recorded:** R-014 (config tests assert structure, never values);
   R-006 corollary ratifying `Attachment` in `request.py` on the import-cycle
   constraint and `PingResult` into the Dictionary.

4. **T-001 marked RESOLVED** in its ticket file, referencing R-014. Closed.

**Tests:** 65 passed, 0 failed (pytest 8.4.1, Python 3.12.11, pydantic 2.11.7),
in 0.15s — up from 63, as the registry file gained two behaviour tests on
synthetic fixtures. 10 adapters, 24 router, 9 registry, 7 smoke, 7 meter, 8
tags. Fully offline. `smoke.py` was NOT run.

**R-014's property was verified, not assumed.** A simulated human config edit —
`architect` swapped to sonnet-5, its ceiling changed to 64000, and a
cross-family `openai/gpt-5.2` fallback added — left the suite at 65 passed. The
registry was then restored and re-verified. Under the old stamped test that
same edit produced three failures; that is precisely the contradiction R-012
created and R-014 removes.

**Stamped files:** `tags.py`, `test_tags.py`, `registry.py`, `test_meter.py`
unchanged. `test_registry.py` was modified under R-014's one-packet
unstamping and is **re-stamped as of this build going green**.

**Deviations:** None. P-004 is now complete — every file in its list is built.

**Self-corrected during the build (recorded because the ledger is only useful
if it records these):** the first hand-typed `registry.toml` carried P-002's
`floor_agent` values — `fallbacks = ["openai/gpt-4o-mini"]`, `max_tokens =
4096` — instead of the packet's `["anthropic/claude-sonnet-5"]` and `64000`.
The structure-only tests do not catch a wrong value, by design, so it was
caught by mechanically diffing against the packet's fenced block rather than by
eye. The file was regenerated directly from the packet block. Standing note for
the floor: transcribing a literal-content block by hand is error-prone; extract
and diff it.

**Note for the packet author:** the shipped `judge` role now has a 128000
ceiling with a `haiku-4-5` fallback, whose documented maximum is 64000. Per the
packet's own "fallback ceilings" contract the router does not clamp, so a
`judge` fallback would carry a max_tokens above that model's limit and the
provider error surfaces through `ProviderCallError`. This is the packet's
stated behaviour, not a defect, and the ping table uses `max_tokens=8` so it
will not surface there. Flagging because it is a real cost only discovered on a
live fallback. Registry authors own this under R-012.

## P-004 amendment — the effort refactor — 2026-08-18

**Built:** Per-role reasoning effort, configured in the registry and passed
through to the provider.

1. **`RoleRoute` gains `effort: str | None = None`.** When present it is
   validated against exactly `low`, `medium`, `high`, `xhigh`, `max`
   (`ALLOWED_EFFORTS` in `registry.py`). An invalid value raises `ValueError`
   naming both the role and the bad value — checked in `load_registry` before
   the model is constructed, matching how `model` and `fallbacks` are already
   validated, so the message is guaranteed rather than inherited from pydantic.

2. **`route_call` sends `reasoning_effort` only when the resolved role sets
   it.** The call is now built as a kwargs dict; the key is added only when
   `route.effort is not None` and is otherwise absent entirely — not `None`,
   not empty. **No thinking field is ever sent.** Demonstrated directly:

   ```
   effort set   -> kwargs sent: ['max_tokens', 'messages', 'model', 'reasoning_effort']
   effort None  -> kwargs sent: ['max_tokens', 'messages', 'model']
   ```

   Effort rides every attempt in the chain, fallbacks included.

3. **Config edits (R-012, human-authorized):** `architect` = `xhigh`,
   `architect_max` = `max`, `judge` = `high`, `floor_agent` = `medium`,
   `default` omitted. **`judge`'s `max_tokens` lowered 128000 → 64000**, which
   closes the ceiling warning raised in the previous entry: its
   `haiku-4-5` fallback documents a 64k maximum, so the old ceiling would have
   turned a rescue into a second failure. The reason is commented in the file.

4. **Tests (offline):** effort set → the fake receives `reasoning_effort` with
   the exact value; effort None → the fake receives no `reasoning_effort` kwarg
   at all; invalid effort in synthetic TOML → `ValueError` naming role and
   value; every allowed level accepted (parametrized); omitted effort stays
   `None`; effort rides fallbacks; no `thinking*` key is ever sent. The shared
   `FakeCompletion` now captures `**kwargs`, which is what makes "this kwarg
   was NOT sent" assertable at all.

**R-014 honoured.** The shipped registry's effort values are never asserted —
only that IF a role sets effort, the level is valid. Rechecked empirically:
editing `architect` from `xhigh` to `low` and deleting `floor_agent`'s effort
entirely left the suite at 78 passed. Registry restored and re-verified.

**Tests:** 78 passed, 0 failed (pytest 8.4.1, Python 3.12.11, pydantic 2.11.7),
in 0.14s — up from 65. 13 registry, 10 adapters, 20 router, 4 effort, 7 smoke,
7 meter, 8 tags, plus parametrized cases. Fully offline. `smoke.py` NOT run.

**Deviations:** None.

**GOVERNANCE — two things this amendment did that need a ruling:**

1. **It modified two stamped files.** `registry.py` is stamped by P-004, and
   `test_registry.py` was re-stamped the moment the last build went green. Both
   had to change: `effort` cannot be added to `RoleRoute` without touching
   `registry.py`, and the invalid-effort test cannot exist without touching
   `test_registry.py`. The instruction was explicit and came from the packet
   author, so the floor executed it — but it is recorded here as an implicit
   one-amendment unstamping of both files, exactly parallel to R-014's
   treatment of `test_registry.py`. **Recommend Cortex record it as a ruling
   and re-stamp both.** `tags.py`, `test_tags.py`, and `test_meter.py` remain
   untouched and verified.

2. **`tests/test_effort.py` is a new file the floor created.** Adding the four
   effort tests pushed `test_router.py` to 328 lines, breaching Law rule 3 —
   the exact breach the P-003 entry predicted and R-009 deferred. The
   amendment specified the tests but not their file. Rather than compact
   `test_router.py` a third time, effort was split into its own file, which is
   what "one file, one job" actually asks for. `test_router.py` is back to 278.
   **Recommend ratification**, on the R-009 precedent.

## FIRST LIGHT — 2026-08-18 (human ran `python smoke.py`)

The Switchboard made real Anthropic calls for the first time. Recorded from
`ledger/meter.jsonl` (6 metered receipts).

**Ping: 4/4 OK.** Every unique model string in the registry answered —
opus-5, fable-5, sonnet-5, haiku-4-5. The registry is wired correctly and the
`.env` key path works.

**Prove 1 — roles: PASSED.** One metered call each:

| role | model | prompt | completion | cost |
|---|---|---|---|---|
| architect | claude-opus-5 | 30 | 14 | $0.0005 |
| judge | claude-sonnet-5 | 30 | 14 | $0.0002 |
| floor_agent | claude-haiku-4-5 | 48 | 201 | $0.0011 |

**Prove 2 — cache: FAILED.** Both calls returned `cached=0` and `creation=0`
against a stable 2,114-token prompt. **Ticket T-002 opened.**

**Prove 3 — attachments: PASSED.** The PNG + PDF call returned a real answer
(1,620 prompt tokens, 158 completion).

**Observation (rides with T-002):** `floor_agent` (haiku) ignored the system
instruction "Reply with exactly: FOUNDRY ONLINE" — 201 completion tokens
against architect's and judge's 14 each, which obeyed exactly. To be resolved
as either a missing system block or model instruction-following.

**Total first-light spend: ~$0.0092.**

## P-005 — Anthropic Polish: Cache Fix (T-002) + Streaming — 2026-08-18

**T-002 root cause, in one sentence:** neither H1 nor H2 — the cache-marked
prefix was ~1,861 tokens against haiku-4-5's 2,048-token minimum cacheable
size, 187 short, so Anthropic silently declined to cache.

**Diagnosis was empirical and cost nothing.** Both hypotheses were refuted
offline before any code changed:

- **H1 refuted.** Our adapter's payload was run through LiteLLM's real
  `AnthropicConfig.transform_request`. The mark survives into the top-level
  `system` parameter as
  `[{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]`.
  `translate_system_message` explicitly copies `cache_control` from list-form
  system blocks — our shape is exactly what it handles. **`adapters.py` needed
  no change and was not touched.**
- **H2 refuted.** A real `litellm.types.utils.Usage` was constructed the way
  LiteLLM builds one for Anthropic and passed to our `_extract_usage`:
  `creation=2114 read=0 -> ours cached=0 creation=2114`, and
  `creation=0 read=2114 -> ours cached=2114 creation=0`. Both field paths are
  correct.
- **Root cause found by measurement.** `litellm.token_counter` put the block at
  1,861 tokens. The observed `prompt=2114` had misled: that is the *total*
  prompt (system + user + framing), while only the marked prefix counts toward
  the minimum. P-004's comment "long enough to clear Anthropic's minimum" was
  true for Sonnet/Opus (1024) and false for Haiku (2048).

**Fix:** the cache paragraph now repeats 60× instead of 30× — **3,721 tokens
against a 2,048 minimum, 82% margin**. The demo prints its own measured prefix
size beside the model's applicable minimum, so a future shortfall is visible
instead of silent.

**Rider resolved — floor_agent:** the system block **is** present in
floor_agent's outgoing request; the same transformation check shows it hoisted
into `system` exactly as for architect and judge. Recorded as **model
instruction-following, not a defect**, and closed. haiku-4-5 is simply less
literal about "Reply with exactly" than opus-5 and sonnet-5. Debug mode prints
per-role system-block presence so it stays checkable.

**Debug mode:** `FOUNDRY_SMOKE_DEBUG=1` makes the cache demo print the outgoing
message structure for call 1 (with `cache_control` visible, block text
truncated — structure, never secrets) and `dump_usage()` of both raw responses,
every field name and value including nested `prompt_tokens_details`. A
`Recorder` wraps the real caller so this needed no change to `route_call`'s
contract.

**Streaming:** `route_call(..., on_chunk=None)`. With `on_chunk` given the call
runs `stream=True` and each text delta is passed to the callback as it lands;
the returned response is still complete — joined content, `model_used`, usage
from the terminal chunk, and exactly one meter record identical in shape to
non-streaming. With `on_chunk` None the `stream` kwarg is absent entirely
(asserted). A raising callback becomes a `RuntimeWarning`, callbacks stop, the
stream still drains and the receipt still lands. On mid-stream failure the
fallback streams and `response.content` holds only the winner's text; the
docstring documents "rerender from response.content on changed model_used".
Prove 4 streams a judge-role count to 10, flushing each delta.

**Tests:** 87 passed, 0 failed (pytest 8.4.1, Python 3.12.11), in 0.14s — up
from 78. 8 new streaming tests; the two cache tests in `test_router.py` were
rewritten to assert against the **real** LiteLLM usage shape observed in
diagnosis — nested `prompt_tokens_details` AND top-level `cache_*` — rather
than a convenience shape that would have flattered either hypothesis. Fully
offline. `smoke.py` NOT run.

**Stamped files:** all untouched — `tags.py`, `test_tags.py`, `test_meter.py`,
`registry.py`, `test_registry.py`, `conftest.py`, `adapters.py`, `meter.py`,
`request.py`, `registry.toml`, `test_adapters.py`, `test_effort.py`,
`test_smoke.py`. **No R-016 flag is needed** — because the root cause was
neither hypothesis, no stamped file had to change.

**Deviations:** None.

**FLAG — two new files, R-017 precedent:** `smoke.py` hit the 300-line ceiling
while absorbing debug mode and prove 4. Per R-017 (topic splits beat repeated
compaction) it was split: `smoke_debug.py` (diagnostics — `Recorder`,
`describe_messages`, `debug_on`, `cache_minimum_for`, the print helpers) and
`smoke_fixtures.py` (the inline PNG/PDF bytes). `dump_usage` stayed in
`smoke.py` because the Dictionary assigns it there. Neither file is in P-005's
list. **Recommend ratification into the file map.**

**FLAG — `test_router.py` is at exactly 300/300.** It has now been compacted in
three consecutive packets. The next test added to it breaches the ceiling with
no room left. Recommend a `test_cache.py` split next packet rather than a
fourth compaction — R-017 already says so.

**RISK for the confirming run (build-to-spec, flagged not fixed):** the packet
states LiteLLM surfaces usage on the terminal chunk, so streaming usage is read
from there and no `stream_options={"include_usage": True}` is sent. If prove 4
reports zero tokens while the text streams correctly, that is the cause, and it
is a one-line packet amendment — not a streaming defect.

**T-002 remains DIAGNOSED, not CLOSED.** Acceptance is empirical: the human
re-runs `python smoke.py` and call 1 must show creation > 0, call 2 cached > 0.

## P-005 defect fix — load_env deleted during the smoke.py split — 2026-08-18

**Defect:** `FOUNDRY_SMOKE_DEBUG=1 python smoke.py` died immediately with
`NameError: name 'load_env' is not defined`. Introduced by this floor in P-005.

**Cause:** when `smoke.py` was split to get under the 300-line ceiling, the
slice that moved the attachment fixtures out ran from the PNG constant to
`class PingResult`. `load_env` sat inside that range. `TINY_PNG_BASE64`,
`_PDF_STREAM`, and `tiny_pdf_bytes` were moved into `smoke_fixtures.py`;
`load_env` was deleted and moved nowhere. Confirmed against the P-005 diff.

**Fix:** `load_env` restored to `smoke.py`, unchanged, where the Dictionary
assigns it. No other file touched; no stamped file touched.

**Why the suite did not catch it:** nothing exercises `main()` or `smoke.py`'s
module surface. `test_smoke.py` tests `ping_model`, `ping_registry`, and
`prove_roles` as units, and every one of them still passed while the script was
unrunnable. An 87-green suite said nothing about whether the program starts.

**Verification added for this fix (run, not yet committed as a test):**
- A static audit of all three smoke modules for unresolved names — clean
  (`__file__` aside, which is a module builtin).
- Every symbol `main()` needs, resolved at import — all present.
- **A full offline dry-run of `main()`** with `litellm.completion` faked,
  `load_env` stubbed, and `METER_PATH` redirected to a temp file. All four
  phases ran, `main()` returned 0, and 7 meter records were written
  (3 roles + 2 cache + 1 attachment + 1 stream). Debug mode was exercised too:
  the cache_control mark and both raw usage dumps printed correctly.

**Tests:** 87 passed, 0 failed — unchanged, because the gap is not in what they
assert. `smoke.py` is 294 lines, still under the ceiling.

**FLAG — recommend a smoke wiring guard.** The dry-run above is the test that
would have caught this, and it needs no network. It belongs in `test_smoke.py`,
which P-005 stamped, so adding it needs an R-016 unstamping. Not done
unilaterally. **Recommend authorizing it** — the defect class is "the script
does not start", which unit tests of its parts structurally cannot see.

## T-002 CLOSED + R-018 streaming amendment — live run 2026-08-18

**T-002 is CLOSED.** The human re-ran `python smoke.py` and prompt caching
works:

```
call 1: cache_creation_tokens = 4142   (cache written)
call 2: cached_tokens         = 4142   (cache read)
```

Both acceptance conditions met. **Root cause confirmed exactly as diagnosed:**
the cache prefix was below Anthropic's minimum cacheable size for the model.
Neither hypothesis was right — the `cache_control` mark was always reaching
Anthropic (H1) and the router's usage field paths were always correct (H2).
Enlarging the prefix past haiku-4-5's 2,048-token minimum was the entire fix,
and the offline diagnosis needed no spend to establish it.

The live 4,142 tokens against the offline estimate of 3,721 is expected and
harmless: `litellm.token_counter` approximates while Anthropic's tokenizer is
authoritative. Both clear 2,048 with margin, which is the point of the fix.

**Rider closed:** the floor_agent system-instruction observation is confirmed as
**model behaviour, not a defect**. The system block is present in the outgoing
request — verified offline against LiteLLM's transformation and again live via
debug mode. haiku-4-5 is less literal than opus-5 and sonnet-5 about "Reply
with exactly".

**R-018 conditional pre-authorization: TRIGGERED and applied.** The live run
streamed text correctly but reported `tokens=0/0`, which is the exact condition
R-018 anticipated. Applied without a new packet, as authorized:

1. `stream_options={"include_usage": True}` added to the streaming call path in
   `router.py`. Without it the provider never attaches usage to the terminal
   chunk, so a streamed call meters a free-looking receipt — the failure mode
   P-003's contract 6 exists to prevent.
2. **The streaming fakes were corrected to the real shape**, which is the part
   that matters more than the one-line fix. With `include_usage` the real
   terminal chunk carries `usage` with **empty `choices`**, not a content chunk
   with a null delta. The fakes now emit exactly that (`_usage_chunk`), so they
   model the API rather than flatter our implementation.
3. Two tests added: streaming asserts `stream_options` is sent; non-streaming
   asserts both `stream` and `stream_options` are absent.

The pre-authorization is now spent.

**Tests:** 88 passed, 0 failed (pytest 8.4.1, Python 3.12.11) — up from 87:
one new streaming test (`stream_options` is sent), plus an added assertion on
the existing non-streaming test. Fully offline. `smoke.py` NOT run.

**Stamped files:** untouched. Only `router.py` and `test_streaming.py` changed,
both P-005 files.

**Deviations:** None.

**Still open — the smoke wiring guard.** The `load_env` defect earlier today
reached the human because nothing exercises `main()`. That recommendation stands
and still needs an R-016 unstamping of `test_smoke.py`. Worth noting that the
usage-reporting bug just fixed is the same class: the offline suite was green
while a real run produced a wrong receipt, because the fakes modelled our
assumption rather than the API.

## R-020 amendment — smoke wiring guard — 2026-08-18

**Built:** The wiring guard authorized by R-020, plus R-019 recorded.
`test_smoke.py` unstamped for this one amendment under R-016.

**Nine tests added**, covering each pass-through the ruling names:

| guard | asserts |
|---|---|
| system blocks | `prove_roles` sends a system message carrying the instruction |
| effort | the role's configured `reasoning_effort` reaches the provider call |
| cache marking | `prove_cache` sends `cache_control` ephemeral, and both calls are byte-identical — a cache demo whose two prompts differ proves nothing |
| attachments | `prove_attachments` sends both an `image_url` and a `file` part |
| stream options | `prove_streaming` sends `stream=True` and `stream_options={"include_usage": True}` |
| meter | every prove phase writes its records |
| module surface | every symbol `main()` uses exists |
| main() end to end | all four phases run, `main()` returns 0, records land |
| ping failure | a failed ping returns 1, the prove phases never run, no meter file |

**The guard was verified against the real defect, not assumed.** `load_env` was
deleted again on purpose and the suite went red immediately — 3 failed, 13
passed, `AttributeError: module 'smoke' has no attribute 'load_env'`. Then
restored and re-verified green. A guard that has never been seen to fail is not
evidence of anything.

**No provider library is imported by these tests.** A fake `litellm` module is
injected into `sys.modules`, so `main()` runs end to end with nothing leaving
the process. A `stub_litellm` fixture does the same for the `prove_cache` tests,
which reach `prefix_tokens`. Without it the suite ran 1.06s; with it, 0.17s.

**R-014 respected in the end-to-end test.** Record counts are derived from the
loaded registry (`len(proven) + 4`), never hardcoded, so a human editing
`registry.toml` under R-012 cannot turn this red. The `main()` guard reads the
real registry, and that is the one place a config-coupled assertion would have
crept back in.

**R-019 applied:** the fakes here mirror the observed API — the streamed
terminal chunk carries usage with EMPTY choices, the shape confirmed when the
`include_usage` amendment was applied, and the usage object carries both the
nested `prompt_tokens_details` and the top-level `cache_*` fields observed in
the T-002 diagnosis. Each is cited in the code.

**Tests:** 97 passed, 0 failed (pytest 8.4.1, Python 3.12.11), in 0.17s — up
from 88. Fully offline. `smoke.py` NOT run.

**Stamped files:** only `test_smoke.py` changed, under R-020's explicit
one-amendment unstamping. It **re-stamps on cold-verified green**. Every other
stamped file untouched.

**Deviations:** None.

**FLAG — `test_smoke.py` is at 298/300.** Two lines of headroom. The next
packet touching it will breach the ceiling; R-018 already pre-authorizes a
`test_cache.py` split for the cache tests, and this file will need the same
treatment — likely `test_smoke_wiring.py` for the guard.

## P-006 — Attachments: Text Kind (.md / .txt) — 2026-08-18

**Supersession:** P-006 (Text Attachments) supersedes the earlier P-006
"OpenAI Family" draft. The packet instructs deleting that file if present.
**It is not present and never has been** — not in the working tree, not on any
branch, not anywhere in git history (`git log --all --diff-filter=A --
packets/` lists only P-001 through P-005). Nothing was deleted; the delete was
a no-op with no target, exactly as with P-004's "First Light" predecessor. The
OpenAI family re-issues as P-007 now that this packet stamps.

**Built:** `Attachment.kind` gains `"text"`, covering `.md` and `.txt`.
`adapters.py` maps both extensions to `text/plain` and emits the same LiteLLM
file/document part the PDF path uses, media type swapped — so the third kind
rides the last user message alongside images and PDFs under the existing
ordering rules. `smoke_fixtures.py` gains the `TINY_MARKDOWN` fixture
(`# Foundry test` / `P-006`) and a `write_attachment_fixtures()` writer; the
smoke attachments demo now sends PNG + PDF + `.md` in one call and asks the
model to name all three file types.

**R-016 unstamping, declared upfront by the packet:** `request.py` is stamped
and widening `Attachment.kind` is impossible without touching it. Exactly that
one file was modified under the one-amendment unstamping; it **re-stamps on
cold-verified green**. Every other stamped file is untouched — verified by
`git diff --stat` across all fifteen, empty.

**R-018 extension invoked:** `test_smoke.py` stood at 298/300, so the
third-kind assertion could not land without breaching Law rule 3. The standing
pre-authorization applied: the R-020 guard moved to
`tests/test_smoke_wiring.py` (243 lines) and `test_smoke.py` fell to 108. The
packet anticipated exactly this and pointed at the same authorization.

**Loading rules are identical across kinds** (contract 1): bytes read from
`path`, base64-encoded, no processing library. A missing file raises
`FileNotFoundError` naming the path; an extension outside the text map raises
`ValueError` naming it. The two extension-mapped kinds now share one
`_media_type` helper rather than duplicating the lookup-and-raise.

**Base64 hygiene proven, not assumed** (contract 4): a 200-line markdown
fixture is encoded and the payload asserted free of `\n` and `\r`. `b64encode`
never wraps — but the API requires newline-free base64, so the suite now holds
that guarantee rather than trusting it.

**Tests:** 105 passed, 0 failed (pytest 8.4.1, Python 3.12.11), in 0.20s — up
from 97. 17 adapters (7 new: markdown → `text/plain` part, payload round-trips
to the original text, `.txt` identical, `.rst` → ValueError naming it, missing
file → FileNotFoundError, no newlines in the payload, all three kinds in order
on the last user message), plus two new wiring assertions covering the third
kind and the reworded three-type prompt. Fully offline. `smoke.py` NOT run.

**Deviations:** None.

**R-021 recorded:** citations and the Files API stay deferred until a consuming
department exists. No renovation without a work order.

**Note for the packet author:** `smoke.py` sat at 296/300, so the third fixture
was written by moving fixture creation into `smoke_fixtures.py` — whose stated
job is exactly the smoke run's inline fixtures (ratified in R-018). `smoke.py`
came down to 294 rather than up. No new file and no new authorization needed;
flagging only because the move was a floor judgment inside the packet's
declared `smoke.py / smoke_fixtures.py` scope.

## P-006 amendment — T-003 fix + R-022 — 2026-08-18

**T-003 CLOSED.** The live run reached PROVE 3 and failed:

```
messages.0.content.3.document.source.base64.media_type:
  Input should be 'application/pdf'
```

**The packet's contract 2 was the defect; the build was faithful to it.**
P-006 specified the text part as "the same LiteLLM file-part shape the PDF path
uses, media type swapped." That shape cannot work: Anthropic accepts
`source.type: "base64"` on a document **only** with
`media_type: "application/pdf"`. Plain text uses a different source type
carrying raw content, so the media type cannot simply be swapped — the PDF
path's shape is base64-only by construction. The floor built exactly what was
written; what was written did not match the API.

**The failure surfaced exactly as the loud-failure design intends.** Content
index 3 is the text part — image and PDF were fine, so the regression was
isolated to the new kind on sight. The fallback chain behaved correctly,
trying haiku then sonnet and reporting that both rejected the same payload,
which reads as a request defect rather than a provider outage. Nothing was
silently dropped, nothing degraded quietly, and the receipt named the exact
JSON path at fault.

**Fix applied (option (a), ruled by the packet author):**

1. Text attachments now emit a native document block —
   `{"type": "document", "source": {"type": "text", "media_type": "text/plain",
   "data": <raw content>}}`. Extension validation is unchanged, so `.rst` still
   raises `ValueError` naming it and a missing file still raises
   `FileNotFoundError` naming the path.
2. Contract 4's base64-hygiene assertion is **void for the text kind only** —
   there is no base64 payload. It still binds for pdf and image, and the test
   was rewritten to cover those two rather than deleted.
3. The three invalidated tests were rewritten to the transformation-verified
   shape, each citing that verification as its observation source per R-019.
   The wiring guard's third-kind assertion was updated to match.

**R-022 recorded and enforced.** Any packet introducing or changing a provider
payload shape must verify it through the provider's real transformation code
offline before the suite counts as green. `test_adapters.py` now runs the
adapter's real output through LiteLLM's real `AnthropicConfig.transform_request`
and asserts: a text document keeps `source.type: "text"`; **no base64 document
source carries a media type other than `application/pdf`** — the exact T-003
defect, now caught offline; and the cache mark survives on the system block.

**Why this ruling matters more than the fix.** Three green-suite-but-broken-live
failures landed in one session — `load_env` (nothing exercised `main()`),
`include_usage` (usage read from a shape the API does not send without it), and
T-003 — and all three shared one cause: the fixture encoded our own assumption,
so it could only ever agree with itself. R-019 already said fakes model the API;
R-022 adds the enforcement step that makes it checkable. The check costs ~1.2s
and no network, and it is the same technique that refuted H1 during the T-002
diagnosis.

**Tests:** 108 passed, 0 failed (pytest 8.4.1, Python 3.12.11), in 1.27s — up
from 105: three R-022 transformation checks added, and the suite now imports
the real litellm for them (0.22s → 1.27s, the price of the guarantee). Every
file under 300 lines. `smoke.py` NOT run.

**Stamped files:** unchanged. Only `adapters.py`, `test_adapters.py`, and
`test_smoke_wiring.py` were touched — all inside P-006's scope, with
`request.py` already re-stamped and untouched by this amendment.

**Deviations:** None.

## P-006 CLOSED — live run 2026-08-18

The human re-ran `python smoke.py` after the T-003 amendment. **All three
attachment kinds work.**

**Prove 3 — attachments:** the model named all three file types it received —
PDF, plain text, and image. The text kind now lands as a native document block
with `source.type: "text"`, which is what T-003's fix established and what
R-022's transformation check now guards offline.

**Prove 2 — cache:** the flip held exactly as in the T-002 close —
`creation=4142` on call 1, `cached=4142` on call 2.

**Prove 4 — streaming:** receipt `tokens=25/65 cost=$0.0007`, so the
`stream_options` amendment (R-018) is still delivering usage on the terminal
chunk rather than a free-looking receipt.

**P-006 is CLOSED.** The Anthropic family is complete and live-proven across
all four phases: ping, roles, cache, attachments (three kinds), and streaming.

## P-007 — Family Two: OpenAI Adapter — 2026-08-18

**Built:** `OpenAIAdapter` — a plain leading system message, no cache marks
anywhere, and all three attachment kinds in OpenAI-native shapes. `adapter_for`
now routes `openai/` → `OpenAIAdapter`, `anthropic/` → `AnthropicAdapter`,
anything else → None. The smoke run drives its cache and attachment demos once
per family present in the registry, and the ping table reports whether each
model is priced. `.env.example` gains `OPENAI_API_KEY=`.

**R-022 verifications — every OpenAI shape run through LiteLLM's real
`OpenAIGPTConfig.transform_request` offline, before green:**

| shape | verified result |
|---|---|
| system | `{"role": "system", "content": "be brief"}` — plain, unwrapped |
| cache marks | `cache_control` absent from the payload **and** from the transformed request |
| image | `data:image/png;base64,…` preserved |
| pdf | file part, `data:application/pdf;base64,…`, filename `page.pdf` |
| text | file part, `data:text/plain;base64,…`, filename `notes.md`, content round-trips to the original bytes |

**Contract 2 — the text shape was discovered, not assumed.** Both candidates
survive the transformation: (a) a file part with a `text/plain` data URL keeps
its content intact, and (b) an inline text part also round-trips. (a) was built,
because it preserves the attachment semantics the other two kinds and the
Anthropic family already have — an attached file with a name, rather than prose
spliced into the prompt.

**The check earned its keep immediately.** LiteLLM injects
`filename: "my_file.pdf"` onto a file part when none is supplied — so a
`.md` attachment would have reached OpenAI **labelled as a PDF**. Supplying the
real filename is preserved through the transformation, so the adapter sets it
from the attachment path for both pdf and text. Nothing in the packet predicted
this; only running the real transformation surfaced it. A third candidate was
never invented — the ticket path stayed unused because (a) survived cleanly.

**Contracts 4, 5, and 6 needed zero production code**, as the packet expected,
and each is now pinned by a test rather than assumed: `reasoning_effort` rides
an `openai/` route unchanged (OpenAI-native, no translation layer); OpenAI's
cached reads arrive under `prompt_tokens_details.cached_tokens`, the path the
extractor already reads, with no creation counter to invent; and a streamed
`openai/` call meters one complete receipt from the terminal usage chunk.

**Ping pricing check:** `PingResult` gains `priced`. LiteLLM's cost map is keyed
**without** the provider prefix — `claude-opus-5`, not
`anthropic/claude-opus-5` — so the lookup strips it and checks both forms. The
table prints `OK (priced)` / `OK (UNPRICED — update litellm pin)` / `FAIL`.
Unpriced is a warning, not a gate, exactly as contract 7 says: the call still
works, the receipt would read `cost=None`, and the human decides.

**R-012 honoured:** `registry.toml` is untouched — verified by `git diff`,
empty. This packet builds capability; the human chooses roles and models.

**Tests:** 140 passed, 0 failed (pytest 8.4.1, Python 3.12.11), in 1.22s — up
from 108. 21 adapters, 15 adapters-openai, 24 router, 18 registry, 15
smoke-wiring, 13 smoke, 10 streaming, 8 tags, 7 meter, 5 cache, 4 effort. Fully
offline. `smoke.py` NOT run.

**Deviations:** None.

**FLAGS — four scope notes, all forced by the 300-line ceiling or by reality:**

1. **Three new files beyond the packet's list**, on the R-017 precedent that
   topic splits beat repeated compaction: `smoke_families.py` (which families a
   registry holds, which role demos each, each family's caching note, and
   whether a model is priced), `smoke_proves.py` (the demo phases, which
   `smoke.py` re-exports so the public surface and the R-020 guard are
   unchanged), and `tests/test_adapters_openai.py` (test_adapters.py stood at
   284). `tests/test_cache.py` is **not** in this list — R-018 pre-authorized
   it, and it was created exactly as ruled when `test_router.py` hit 300.
   **Recommend ratification of the three.**
2. **`tests/test_streaming.py` was modified**, though the packet named only
   `test_router.py` / `test_cache.py` for the streaming test. `test_router.py`
   could not hold it under the ceiling, and `test_streaming.py` is the
   topic-correct home. Flagging the placement deviation.
3. **`.env.example` lives at the project root, not `switchboard/`** as the
   packet's file map says — that path was set by the human's P-004 amendment
   and R-013. The root file was edited; no file was created under
   `switchboard/`.
4. **`smoke_proves.py` imports `dump_usage` lazily** from `smoke.py`, because
   the Dictionary pins `dump_usage` to `smoke.py` while `smoke.py` imports the
   demos — a module-level import would close the cycle. Same lazy-import
   pattern as R-008.

## P-007 amendment — demo role selection by price, not max_tokens — 2026-08-18

**`max_tokens`-as-cost-proxy is retired.** It silently moved the smoke demos
from haiku ($1/MTok) to sonnet ($2/MTok) when P-006's fallback-ceiling change —
made for an entirely unrelated reason, keeping `judge` compatible with its
haiku fallback — dropped `judge` to 64000 and created a three-way tie that
declaration order resolved in `judge`'s favour. Nobody chose that. A ceiling is
not a price, and a proxy that happens to correlate stops correlating the moment
something unrelated moves.

**Ruled fix applied:** `demo_role_for` now ranks each family's roles by
`input_cost_per_token` from LiteLLM's cost map, through the existing
prefix-stripping lookup (R-023's known seam). Unpriced models sort last. If
every model in a family is unpriced the old `max_tokens` rule still selects
one, so the demo always runs. Ties break by declaration order, which is
harmless now that equal price means equal cost.

Verified against the shipped registry: the anthropic demo role returns to
`floor_agent` (haiku, 1e-06) instead of `judge` (sonnet, 2e-06).

**The regression is guarded, not just fixed.** The new test's fixture is built
so the retired rule gets it wrong — the pricier model carries the *lower*
ceiling — so the old proxy would pick the $2 model and the price rule picks the
$1 one. Demonstrated both ways before committing.

**Tests:** 144 passed, 0 failed (pytest 8.4.1, Python 3.12.11), in 1.30s — up
from 140. Four new selection tests plus one R-022-style check that the real
cost map prices every shipped model through the stripping lookup. The four fast
tests install a synthetic cost map via the established `sys.modules` stub, so
only the R-022 check touches the real map; that one asserts structure, never
prices (R-014) — the human may repoint any role.

**R-012 honoured:** `registry.toml` untouched. The fix is in the selection
rule, not in gaming the registry to win a tie-break.

**Deviations:** None. Only `smoke_families.py` and `tests/test_smoke.py`
changed.

## Registry edit + guard fix — the single-family assumption — 2026-08-18

**Registry (human config, R-012):** two OpenAI roles added — `judge_second`
(gpt-5.6-terra, fallback luna) giving the design doc's cross-family judge seat
an actual entry, and `floor_agent_second` (gpt-5.6-luna) as the cheapest
capable brain we run. `openai/gpt-5.6-sol` appended to `architect`'s fallbacks
as a cross-family safety net — peer tier at $5/$30, a hedge against an
Anthropic outage rather than a cost move. The registry now holds 7 roles across
2 families and pings 7 unique models.

Every fallback chain was checked against its role's ceiling before committing:
no risks. Sol's 128k output cap matches architect's ceiling exactly, so the new
chain cannot repeat the `judge`/haiku mismatch P-006 had to correct.

**The config edit turned the suite red, and the redness was the guard's own
defect.** `test_main_runs_every_phase_end_to_end` asserted
`len(records) == len(proven) + 4`, where `4` silently meant "one family × (2
cache + 1 attachments) + 1 stream". Adding a second family made it wrong. The
assertion now derives the family dimension too — two cache calls per family,
plus an attachments call for each family that has an adapter, plus one stream —
so an adapterless family, or a third family later, adjusts the expected count
automatically.

**Third instance of one disease, and the most instructive.** A value that
happened to be right while the world had one shape: 4096 `max_tokens` in P-002,
`max_tokens`-as-price in P-007, and now `4` as family arithmetic. What makes
this one worth remembering is that **the test's own comment claimed
config-independence while the arithmetic silently disagreed** — it read
"Counts derive from the registry, never from hardcoded config values, so a
human editing registry.toml under R-012 cannot turn this red." The intent was
right; one dimension was missed. A comment asserting a property is not the
property.

**The falsifier was a legitimate config edit, not a test.** Which is the
practical lesson worth adopting as habit: config changes get made against the
suite first and the live run second. The suite earned that trust here — it went
red on a lawful edit and the failure pointed at its own defect rather than at
the config, which is the failure-isolation the factory exists to deliver.
Recorded as the R-014 corollary.

**Tests:** 144 passed, 0 failed. Every file at or under 300 lines. `smoke.py`
NOT run — the live run is the human's.

## P-007 amendment — T-004 fix + R-024 — 2026-08-18

**The live run proved the Switchboard multi-provider in six of seven phases.**
Ping 7/7, all priced, Sol included — so the key reaches it. All five roles
answered `FOUNDRY ONLINE`, both OpenAI seats among them. Anthropic's marked
cache flipped `creation=4142 → cached=4142`. **OpenAI's automatic prefix cache
flipped too — `cached=0 → cached=3674` — read with zero router changes**,
because OpenAI reports it under `prompt_tokens_details.cached_tokens`, the path
the extractor already used. `creation=0` on both calls, exactly as
`test_cache.py` asserts from the docs: OpenAI has no creation counter and the
extractor does not invent one. Contract 5 validated live.

**T-004 CLOSED.** PROVE 3 on the openai family failed: OpenAI's file content
part accepts `application/pdf` only, and rejected the `text/plain` data URL at
`content[3]` — the text attachment. Image and PDF were accepted; the failure
was isolated to the new kind on one family.

**The packet's contract 2 delegated the choice to a verification that could not
settle it.** It asked which candidate "is accepted", and the instrument offered
was the transformation check. Both candidates survived that check, so the floor
chose (a) on semantics. But **LiteLLM performs no MIME validation on file
parts** — its whole file-part handler injects a default filename and forwards
everything else untouched. A transformation that faithfully passes an invalid
payload is behaving correctly, so the check reported green on a shape the
provider would refuse. That gap is what R-024 now names: **fidelity is not
acceptance.** They coincide only where the transformation validates —
Anthropic's does, OpenAI's does not.

**Fix applied (candidate b, ruled):** the OpenAI text kind travels as an inline
text part inside a fixed mechanical frame — filename line, content, end line —
defined once as a module constant and pinned by test so it can never drift. It
is the other candidate the packet named, not an invented third shape. Extension
validation is unchanged, so `.rst` still raises `ValueError` naming it; the
media type simply never reaches the wire.

**The regression guard is the assertion that would have caught it:** no file
part is ever non-PDF, checked through the real transformation across all three
kinds. R-022's filename-injection catch is retained against the pdf kind, where
it still applies.

**Two providers, one rule, now booked as a prediction.** T-003: Anthropic's
base64 document source is PDF-only. T-004: OpenAI's file part is PDF-only.
Document and file parts are for PDFs; text travels as text. R-024 books this
for Gemini/P-008 — a docs-first pass should ask that question explicitly rather
than rediscover it live.

**Layered defense worked as designed.** R-022 caught the `my_file.pdf` filename
injection offline, before ship. Smoke caught the MIME rejection live, on the
one phase no offline instrument could reach. Neither replaces the other, and
the failure isolated itself to a single content index on a single family.

**Tests:** 145 passed, 0 failed (pytest 8.4.1, Python 3.12.11) — up from 144.
Every file at or under 300 lines. `smoke.py` NOT run.

**Deviations:** None. Only `adapters.py`, `test_adapters_openai.py`, and
`test_smoke_wiring.py` changed.

## T-004 CLOSED — two-family milestone — live run 2026-08-18

**T-004 CLOSED.** PROVE 3 on the openai family passed: the model named all three
file types and read back the filename `notes.md`. The labelled frame is doing
the job the file part's `filename` field used to do, so candidate (b) loses
nothing that (a) carried. Confirmed by the only authority that could settle it —
the provider (R-024).

**The Switchboard is proven multi-provider.** Seven models pinged and priced
across two families, five roles proven, both cache mechanisms live, and a
streaming receipt of `tokens=25/76 cost=$0.00081`.

**Observed provider behaviour worth recording, not acting on:** OpenAI's
automatic cache **persists across program runs**. Call 1 of the cache demo
reported `cached=3674` immediately — a warm prefix left by the previous run,
not a cold write. Anthropic's marked cache showed the expected cold flip in the
same run. The demo's printed expectation ("call 1 creation > 0, call 2 cached >
0") is Anthropic-shaped and does not describe this; the label already says the
values are reported, not asserted, so the run is truthful as printed. Recorded
as observed provider behaviour for whoever next touches the cache demo.

## P-008 — Family Three: Gemini Adapter — 2026-08-18

**Built:** `GeminiAdapter` — a plain leading system message, no cache marks,
and all three attachment kinds as inline-data parts. `adapter_for` routes
`gemini/` to it; the other families and the unknown-family case are unchanged.
`.env.example` gains `GEMINI_API_KEY=`. `gemini-2.5-pro` appears nowhere in any
build artefact.

**The registered prediction BROKE, exactly as the packet suspected it might.**
R-024 predicted "document and file parts are PDF-only; text travels as text",
observed on Anthropic (T-003) and OpenAI (T-004). Gemini is natively
multimodal, and all three kinds arrive the same way:

```
image/png · application/pdf · text/plain   →  all inline_data
```

Text keeps its document semantics here rather than being flattened into the
labelled prose frame T-004 forced on OpenAI, so contract 2's preferred
candidate (a) was built. **The pattern is provider-specific, not universal** —
two of three families constrain file parts to PDF, the third does not. Booking
it as a prediction was still right: it made the question explicit and cheap to
answer, and being wrong took one transformation dump to establish.

**Contract 1 — cache marks are dropped.** `cache_control` survives nowhere in
Gemini's body and no `cachedContent` key appears. The packet's specified path
was taken: build without marks, rely on implicit caching, and the family's
cache note reads accordingly.

**R-022 evidence path, worth recording for the next family:** Gemini's
`transform_request` raises `NotImplementedError("Vertex AI has a custom
implementation")`. The obvious entry point is a dead end; the real builder is
`sync_transform_request_body`, which every R-022 check in
`test_adapters_gemini.py` now calls.

**Two contracts are NOT built — filed as T-005:**

1. **Contract 3 (effort).** `low/medium/high` map one-for-one onto Gemini's
   `thinkingConfig.thinkingLevel`. **`xhigh` and `max` raise
   `ValueError: Invalid reasoning effort`** — not dropped, not mistranslated,
   hard-raised before a request leaves the process. The STOP gate fired. No
   client-side collapse was invented, and no test pins the raising behaviour,
   which would enshrine a defect as expected. The three working levels are
   pinned. No blast radius today: the only `xhigh`/`max` roles are
   `anthropic/`.
2. **Contract 4 (forbidden parameters).** LiteLLM injects
   `temperature: 1.0` into `generationConfig` **unconditionally** — with no
   parameters supplied at all. Contract 4's assertion ("neither from us nor
   injected by LiteLLM defaults") cannot pass. Our half is pinned: the adapter
   contributes no sampling parameters. The injection is LiteLLM's, and
   stripping it edits a payload the router does not own. Pure R-024 territory —
   LiteLLM still lists `temperature` as supported for this model while the
   provider docs say 3.6+ removed it, and only the live run can settle which
   is right.

**Smoke needed ZERO structural changes** — the packet said that was the point
of the per-family design, and it held. The third family joins the ping table,
the per-family cache demo, and the three-file attachments demo through the
existing iteration alone. No `smoke.py`, `smoke_proves.py`, or
`smoke_families.py` edits.

**R-012 honoured:** `registry.toml` untouched, verified by empty diff.

**Tests:** 165 passed, 0 failed (pytest 8.4.1, Python 3.12.11) — up from 145.
17 gemini adapters, 21 anthropic adapters, 16 openai adapters, 24 router, 18
registry, 17 smoke, 15 smoke-wiring, 11 streaming, 8 tags, 7 cache-extraction,
7 meter, 4 effort. Every file at or under 300 lines. Fully offline.
`smoke.py` NOT run.

**Deviations:** None built outside scope; two contracts deliberately unbuilt
and ticketed.

**FLAGS:**

1. **`tests/test_cache.py` and `tests/test_streaming.py` were modified** for
   contracts 5 and 6, though the packet's file map names neither. They are the
   topic-correct homes for cached-token extraction and streamed metering, and
   R-023 ratified topic-correct over packet-literal. Flagging the placement.
2. **`adapters_gemini.py` was not needed.** `adapters.py` holds all three
   families at 278 lines, so the R-017 pre-authorisation went unused.

## P-008 amendment — R-025: effort ceilings validated at load — 2026-08-18

**T-005 CLOSED.** The failure shape was the defect, not just the failure. A role
written legally under R-012 with `effort = "xhigh"` on a `gemini/` model raised
`ValueError: Invalid reasoning effort` from inside LiteLLM, mid-run, when an
architect call fired. The config was lawful; the diagnosis arrived at the worst
possible moment and named nothing useful.

**Applied:** each adapter now declares its family's effort vocabulary —
Anthropic five levels, OpenAI five, Gemini three — and `load_registry`
validates every role's effort against its primary model's family ceiling. What
a human sees now, at load:

```
role 'judge_third': effort 'xhigh' exceeds the 'gemini' family ceiling (low, medium, high)
```

Role, family, and ceiling, before any call is made. **A family without an
adapter is not validated** — we do not know its vocabulary, and inventing one
would be worse than staying silent.

**R-014 compliant by construction:** the check tests legality against family
rules, never which value the human chose within them. The shipped registry's
`xhigh` and `max` roles load unchanged, because they are `anthropic/`.

**The discriminating test does the discriminating:** one synthetic registry
fails at `xhigh` naming role, family and ceiling, and **the same registry loads
when the effort drops to `high`**. A test that only checked the failure would
not prove the rule admits the legal case.

**Cross-family fallback ceilings stay the human's** (R-012), the same treatment
the `max_tokens` ceiling got — surfaced by the ping and prove path rather than
enforced in code.

**Temperature booked, not fixed.** Our half is pinned: the adapter contributes
no sampling parameters. LiteLLM's injected `temperature: 1.0` remains an open
R-024 acceptance question, and the live run is the gate — tolerated-but-noted
if Gemini 3.7 accepts, T-006 with the exact error if it rejects. Roughly
$0.001 buys the answer.

**R-016 flag:** `registry.py` and `test_registry.py` are stamped and both had to
change — the validation belongs at load, which is `registry.py`, and its tests
belong with the registry's. One-amendment unstamping of exactly those two;
they re-stamp on cold-verified green.

**Tests:** 170 passed, 0 failed (pytest 8.4.1, Python 3.12.11) — up from 165.
Five new registry tests: the ceiling rejection, the same-registry-passes case,
five-level families accepting `max`/`xhigh`, the unvalidated adapterless
family, and an R-014-safe check that every shipped role respects its family's
ceiling. Every file at or under 300 lines. `smoke.py` NOT run.

**Deviations:** None.

## THREE-FAMILY RUN — live 2026-08-18

**8/8 pinged and priced** across anthropic, openai and gemini. **Six roles
proven**, `judge_third` among them, every one answering `FOUNDRY ONLINE`. **All
three families named all three file types.** Streaming receipt
`tokens=25/42 cost=$0.00047`. **Total spend: $0.022.**

**Both open questions CLOSED by the run:**

1. **Temperature — tolerated.** LiteLLM injects `temperature: 1.0` into every
   Gemini request, and every Gemini call succeeded: ping, role, both cache
   calls, attachments. Gemini 3.7 tolerates the field rather than rejecting it,
   so contract 4's unsatisfiable assertion resolves to tolerated-but-noted and
   **no T-006 is opened**. R-024's acceptance question answered by the only
   authority that could answer it, for roughly $0.009.
2. **The prediction break — confirmed on the wire.** Gemini named
   *"Text / Markdown document (Plain Text)"*, so `text/plain` `inline_data` is
   genuinely **accepted**, not merely faithfully translated. R-024's pattern is
   provider-specific, now proven live rather than inferred from a dump.

**Cache behaviour, booked as observed:**

| family | mechanism | call 1 | call 2 |
|---|---|---|---|
| anthropic | explicit mark | `creation=4142` | `cached=4142` |
| openai | automatic prefix | `cached=0` | `cached=3674` |
| gemini | implicit only | `cached=0` | `cached=0` |

OpenAI's prefix was **cold** this run, where the previous run opened warm from
a prior process — so that cross-run persistence is time-limited, not
indefinite. Gemini produced **zero hits** on two back-to-back identical
~3.7k-token prefixes. Reported, not explained: the threshold or timing of its
implicit cache is unknown to us, and guessing would be worse than saying so.

**Defect in the P-008 build, found by reading the output rather than the
tests.** Contract 1 specified the Gemini cache label — "implicit caching only;
explicit marks not supported via this path". The adapter was built without
marks and the finding was recorded, but the note was never wired into
`_CACHE_NOTES`, so the demo printed the fallback **"caching behaviour unknown
for this family"**. That is wrong in the way that matters most: we know
precisely what this family does, and the output claimed we did not. Every test
passed while the run told the user something false — no assertion covered the
label, so nothing caught it.

**Fixed:** the gemini note now carries the contract-1 text plus the live
observation, and a test pins that every family with an adapter gets its own
note rather than the fallback. The note says what we know and what we merely
observed, without dressing the observation up as an explanation.

**Registry:** `judge_third` added by the human under R-012 — Gemini 3.7 Flash
at `effort = "high"`, inside the three-level ceiling R-025 now validates at
load. Eight roles, three families, eight models pinged.

**Tests:** 171 passed, 0 failed — up from 170, the new one being the cache-note
guard. `smoke.py` NOT run as part of this amendment; the run above was the
human's authorised invocation.

---

## P-009 — Family Four: xAI (Grok) Adapter

**Built:** 2026-08-18. Fully offline; `smoke.py` NOT run.

**Transformation entry point (R-022, recorded as the packet requires):**
`litellm.llms.xai.chat.transformation.XAIChatConfig.transform_request`
(`litellm/llms/xai/chat/transformation.py`). Unlike Gemini's config — whose
`transform_request` raises `NotImplementedError`, forcing us to
`sync_transform_request_body` in P-008 — xAI's is the real path and is called
directly. Every emitted shape in `test_adapters_xai.py` goes through it.

**Contract 2 — image:** the OpenAI-compatible base64 data URL survives the
transformation byte-identical; the fixture decodes the URL and compares to the
original PNG bytes rather than to a string we wrote.

**Contract 3 — text, and why candidate (b) won.** Both candidates survive
transformation, so *fidelity could not decide it*: LiteLLM performs no MIME
validation on the xai path, exactly as it performed none on the OpenAI path
that produced T-004. Docs decided it (R-024). xAI documents text and image
input and no file/document input type, so candidate (a) — a file part carrying
a `text/plain` data URL — would have depended on an undocumented shape. Built:
candidate (b), the same labelled frame T-004 settled for OpenAI, now shared as
`_framed_text_part`.

**Contract 4 — the prediction's inverse case, and it inverted.** The registered
cross-provider prediction ("document and file parts are PDF-only; text travels
as text") held on Anthropic (T-003) and OpenAI (T-004) and broke on Gemini,
which accepted `text/plain` as `inline_data`. On xAI it inverts in the other
direction: there is **no document part at all**. LiteLLM will nonetheless carry
a file part for an xai model without complaint — it even injects
`filename: "my_file.pdf"`. `test_litellm_would_have_carried_a_pdf_part_without_complaint`
pins that fact deliberately, because it is the cleanest demonstration of R-024
this codebase has: a transformation check alone would have shipped a shape the
provider does not document. So the refusal is ours to make, at the adapter, and
it is loud — naming kind, family, reason, and path — and it is checked *before*
the file is opened, since the family cannot take PDFs whether or not the file
exists.

**Contract 5 — effort ceiling is the intersection, no superset.**
`GrokAdapter.EFFORT_LEVELS = ("low", "medium", "high")`. Grok 4.6 accepts
`xhigh`; Grok 4.5 does not. Declaring the superset would let a lawful config
(4.5 at `xhigh`) load clean and explode at call time — the exact failure R-025
exists to prevent. Empirically confirmed that nothing below our registry would
catch it: `test_litellm_itself_would_not_have_caught_it` shows LiteLLM passing
`xhigh`, `max`, and even `not-a-level` straight through for xai, validating
none. The discriminating pair (same synthetic registry, `xhigh` fails at load
naming role/family/ceiling, `high` loads clean) is the R-025 precedent.
**Booked as a future ruling candidate:** per-model effort vocabularies, only if
a real workload wants `xhigh` on 4.6. A 4.6 user temporarily loses it.

**Contract 6 — the ticks question, resolved by evidence.**
`cost_in_usd_ticks` appears **nowhere in litellm 1.97.0** — a grep over the
installed package returns no files. There is no observed shape, so per the
contract **no speculative parsing was built**; booked as an R-024 note. What
was built is the safe half: a test proving that a usage object carrying an
unknown `cost_in_usd_ticks` attribute neither crashes the extractor nor is
mistaken for dollars — cost still comes from the cost function. If a future
litellm surfaces the field, the live debug dump settles it and an amendment
captures it.

**Contract 7 — usage/cache:** zero router changes, as predicted. xAI is
OpenAI-compatible, so cached input arrives at
`prompt_tokens_details.cached_tokens` — the path the extractor already reads.
Asserted with an xai-shaped fake rather than assumed.

**Contract 8 — streaming:** family-agnostic, unchanged; one offline test at the
fourth prefix.

**R-023 seam, inverted for this family.** `xai/grok-4.6` and `xai/grok-4.5` are
priced in the cost map **with** the `xai/` prefix — bare `grok-4.6` is absent.
That is the opposite keying from Anthropic and OpenAI. `_cost_entry` already
checks both forms, so nothing broke; recorded because the seam is now known to
cut both ways. Note also that `xai/grok-4.1-fast` is **not** priced — it would
raise the UNPRICED warning in the ping table if a human routes to it.

### Flags for Cortex

1. **`adapters.py` split twice, both under standing authorisations.**
   `adapters.py` stood at 297 lines with three families; adding the fourth
   reached 322. P-009 pre-authorised `adapters_xai.py` (R-017). That alone left
   the file 22 over, so I also used **P-008's standing pre-authorisation for
   `adapters_gemini.py`**, which was granted *conditional on the 300 ceiling
   forcing it* and went unused at the time. The ceiling is forcing it now, so
   the condition is met — but the relocated Gemini code is P-008's, not this
   packet's, so it is flagged rather than assumed. `adapters.py` is now 292;
   the public surface is unchanged (a PEP 562 `__getattr__` re-exports both
   `GeminiAdapter` and `GrokAdapter`, and a test asserts the re-export is the
   same object as the direct import). The re-export is lazy on purpose: the
   family modules import helpers from `adapters.py`, so a top-level import
   either way would close the cycle.

2. **`smoke_proves.py` and `smoke_families.py` modified, neither in the packet
   file map.** Contract 1 requires the xai `_CACHE_NOTES` entry, which lives in
   `smoke_families.py`; the test list requires the attachments demo to send
   only accepted kinds and print a note for the refused one, which lives in
   `prove_attachments` in `smoke_proves.py`. Both files were split out of
   `smoke.py` in P-005/P-007, after which the map stopped tracking them. R-016
   flag with the reason cited; no behaviour beyond the two contracts was
   touched.

3. **`test_smoke_wiring.py` split (R-017).** It sat at exactly 300; the fourth
   family's wiring assertions had nowhere to go. Its per-family half moved to
   `tests/test_smoke_wiring_families.py` at the seam the P-007 comment already
   marked. `SmokeFake` is imported from its parent module rather than copied —
   one fake, one definition, which is R-009's intent, though R-009's letter
   says shared fakes live in `conftest.py` and `conftest.py` is not in this
   packet's map. Flagged for a ruling on which reading governs.

4. **Contract 9's registry-adjacent notes are recorded here, not in
   `registry.toml`.** The instruction was explicit that this build makes no
   registry edits (R-012). For the human, then: **the 200K long-context cliff**
   — above 200K input tokens xAI doubles the rate, so a large-context role on
   Grok is not priced the way the map suggests; **Grok 4.5 is EU-restricted**
   on the API console; **Grok 4.1 Fast** offers a 2M window at volume pricing
   ($0.20/$0.50) but is **unpriced in litellm 1.97.0**, so its receipts would
   read `cost=None` until the pin moves.

**Files:** `adapters.py` (292), `adapters_gemini.py` (70, new),
`adapters_xai.py` (74, new), `smoke_families.py`, `smoke_proves.py`,
`.env.example` (+`XAI_API_KEY=`, placeholder only), `test_adapters_xai.py`
(278, new), `test_smoke_wiring_families.py` (106, new), `test_smoke_wiring.py`,
`test_smoke.py`, `test_cache.py`, `test_streaming.py`. No registry edits, no
new dependencies, no keys, no network.

**Tests:** 192 passed, 0 failed — up from 171. Every file under the 300-line
ceiling. `smoke.py` NOT run; the live gate on xAI (R-024) remains the human's.

---

## Cache reporting defect + the cached=128 watch, resolved from the meter

**2026-08-18, after the P-009 live runs. Offline diagnosis; `smoke.py` NOT run.**

### The defect: the cache demo printed Anthropic's expectation at every family

`prove_cache` printed, unconditionally:

```
expected: call 1 creation > 0, call 2 cached > 0 (reported, not asserted)
```

Only Anthropic reports a cache-**creation** counter, because only Anthropic
takes an explicit `cache_control` mark. `test_cache.py` already pinned that
openai, gemini, and xai read creation as a **structural zero** — so for three
of four families this line promised something that can never happen. Worse, it
inverted the reading of a success: a textbook provider-side cache hit prints
`creation=0`, directly under a line saying creation was expected above zero.

This is the same defect shape as the missing Gemini cache label: every test
passed while the output told the operator something false about a family we
understand precisely. Nothing asserted the printed text, so nothing caught it.

**Fixed:** `cache_expectation_for(family)` in `smoke_families.py`, beside the
notes, so family knowledge stays in one place. Anthropic keeps its expectation;
every other family gets "no creation counter on this family — cached > 0 once
the provider's own cache engages, on either call." Pinned by a test asserting
Anthropic is promised a counter and no other family is.

### The cached=128 watch: resolved as a floor plus a delayed cache, not a defect

R-027 logged xAI's constant `cached=128` as observed-not-explained. The meter
ledger settles it — six xai records across two runs:

| run | prompt | completion | cached | cost |
|---|---|---|---|---|
| 14:53 | 219 | 128 | **128** | 0.001014 |
| 14:53 | 3936 | 470 | **128** | 0.010500 |
| 14:54 | 3936 | 435 | **128** | 0.010290 |
| 15:05 | 219 | 172 | **128** | 0.001278 |
| 15:06 | 3936 | 1199 | **3840** | 0.009306 |
| 15:06 | 3936 | 476 | **3840** | 0.004968 |

Two facts fall out:

1. **128 is a floor, not a prefix hit.** It appears on a 219-token prompt in
   both runs, where our ~3.7k cache block is not even present. A fixed
   system-side segment is now the well-supported reading rather than a guess.
2. **xAI's prefix cache is cross-run persistent but not immediately
   available.** Within run 1 the byte-identical pair stayed at 128 across a
   ~14-second gap. In run 2, twelve minutes later, **call 1 already opened warm
   at 3840 of 3936 tokens** — so the run-1 prefix had been cached, just not in
   time for run 1 to see it. Same shape as the OpenAI cross-run persistence
   already recorded, with a slower onset. Threshold still unknown; the note now
   says exactly this much and no more.

**The discount is real and our meter is truthful.** All six records reproduce
to the cent under $2/$6 per MTok with cached input at $0.50: predicted
`(prompt - cached)·$2 + cached·$0.50 + completion·$6` matches every recorded
`cost_usd` exactly. The two 3840-cached calls cost less than the 128-cached
ones despite similar work — the cache is paying.

The xai cache note now carries both observations. It says what we measured and
declines to explain the timing, which we did not measure.

### Flag: `test_smoke.py` split (R-017)

Adding the expectation guard took it to 318. Its `smoke_families.py` unit tests
moved to `tests/test_smoke_families.py` — one test module per source module.
Ping-table and fixture tests stayed. Under R-026 the split inherits its
parent's map entries.

**Files:** `smoke_families.py`, `smoke_proves.py`, `tests/test_smoke.py` (198),
`tests/test_smoke_families.py` (176, new). No registry edits, no adapter
changes, no new dependencies.

**Tests:** 194 passed, 0 failed — up from 193. `smoke.py` NOT run.

---

## P-010 — Streaming by default, all families

**Built 2026-08-18** on the ruling "option 1, always stream with opt-out", with
its mandatory per-family acceptance rider. `smoke.py` NOT run.

### The flip

`route_call` gains `stream: bool = True`. Every call now streams. Without an
`on_chunk` callback the deltas are consumed internally and the assembled text
is returned, so the API surface is unchanged for existing callers.
`stream=False` makes exactly the single blocking call the router used to make
when no callback was supplied — the escape hatch, and a tested one.

`_stream_call` now takes `on_chunk: ... | None`, since most calls have no
consumer for the deltas. The fallback-mid-stream partial-text behaviour is
unchanged and stays documented as-is.

### What the flip cost, and why it is worth stating

Streaming was live-proven on **Anthropic only**. The default puts all four
families on a path where **usage arrives on the terminal chunk rather than the
response object** — the exact path that reported `tokens=0/0` before R-018.
Every ordinary call in the system now depends on it, so:

- **PROVE 4 is now per-family**, running inside `prove_families` once per family
  present in the registry, via that family's existing demo role. The lone
  end-of-run streaming demo in `main()` is gone. This is the R-024 acceptance
  gate for the flip.
- **`FakeCompletion` now models both shapes** (R-019): an iterator of chunks
  when `stream=True`, a response object otherwise, with the terminal chunk
  carrying EMPTY choices as LiteLLM really sends. A fake that only returned a
  response object would have tested a path the system no longer takes by
  default.
- **`test_cache.py`'s per-family usage fixtures now run through the streamed
  path** via a shared `provider()` helper, so cache extraction is proven where
  it actually happens now, not only on the opt-out path.

### Live acceptance: 9 of 9 models, all four families

Run directly against the API with the human's authorisation — **not smoke.py**,
a standalone probe, one 512-token streamed call per distinct model in the
registry, primaries and fallbacks alike:

| model | chunks | text | terminal usage | verdict |
|---|---|---|---|---|
| anthropic/claude-opus-5 | 10 | yes | yes | OK |
| anthropic/claude-sonnet-5 | 3 | yes | yes | OK |
| anthropic/claude-fable-5 | 4 | yes | yes | OK |
| anthropic/claude-haiku-4-5-20251001 | 4 | yes | yes | OK |
| openai/gpt-5.6-sol | 6 | yes | yes | OK |
| openai/gpt-5.6-terra | 6 | yes | yes | OK |
| openai/gpt-5.6-luna | 6 | yes | yes | OK |
| gemini/gemini-3.7-flash | 4 | yes | yes | OK |
| xai/grok-4.6 | 15 | yes | yes | OK |

**Every model streamed and every model attached usage to its terminal chunk.**

### Finding: Gemini spends its token budget on reasoning before any text

The first probe pass ran at `max_tokens=32` and Gemini returned **29 completion
tokens and zero visible text**, `finish_reason="length"`. Probed rather than
assumed — dumping the raw chunks showed all 29 were `reasoning_tokens`. At
`max_tokens=512` the same prompt emitted "streaming works" after 72 reasoning
tokens.

So `max_tokens` on Gemini must cover **reasoning plus visible output**; a cap
that only fits the answer yields an empty string, truthfully metered, with
`finish_reason="length"`. Not a streaming defect and not P-010's to fix — the
registry's gemini role is at 64000, far above the cliff. Recorded because a
future human lowering a Gemini ceiling would meet it, and an empty response
with a healthy receipt is a confusing thing to debug from cold.

### Flags for Cortex

1. **`test_streaming.py` split (R-017).** The P-010 contract tests took it to
   345. Its per-family streamed fixtures moved to
   `tests/test_streaming_families.py` at the seam the packet comments already
   marked. Under R-026 the split inherits its parent's map entries.
2. **`tests/conftest.py` modified.** `FakeCompletion` had to learn the
   streaming shape or the default path would go untested; `streamed()` and
   `provider()` were added beside it so no test copies a fake (R-026 item 3).
   Flagged because conftest is shared by every test file.

**Files:** `src/switchboard/router.py` (261), `smoke.py`, `smoke_proves.py`,
`tests/conftest.py`, `tests/test_streaming.py` (227),
`tests/test_streaming_families.py` (143, new), `tests/test_cache.py`,
`tests/test_smoke_wiring.py`, `tests/test_smoke_wiring_families.py`. No
registry edits, no adapter changes, no new dependencies.

**Tests:** 200 passed, 0 failed — up from 195. Every file under the 300-line
ceiling. `smoke.py` NOT run; per-family PROVE 4 awaits the human's run.

---

## P-009.5 — The Model Matrix

**Built 2026-08-18.** Fully offline; `smoke.py` NOT run — the human runs the
matrix.

### What it is

`smoke.py --matrix` sweeps **every model in the registry, primaries and
fallbacks alike, deduplicated** — reusing `unique_models`, which already existed
for the ping table. Per-family demos answer "does this family work". The matrix
answers "does this MODEL work", which becomes a different question the moment a
human repoints a role or leans on a fallback.

Per model: one call per attachment kind, then the byte-identical two-call cache
demo with the existing prefix. Five calls for a full-adapter model, fewer when
kinds are refused by design. Output is one grid — model × [image, pdf, text,
cache c1, cache c2, cost] — printed and appended to `ledger/matrix-runs.md`.

`--matrix` is **additive**: the default run is byte-for-byte unchanged, guarded
by a test asserting a default run never prints `=== MATRIX` and never creates
the artifact.

### Decisions the packet did not specify, and how they were resolved

1. **One call per kind, not one call carrying three.** The grid has separate
   image/pdf/text columns, so a combined call would blank all three cells on a
   single failure and hide which kind broke.
2. **`max_tokens` is inherited from the role that owns the model**, primary or
   fallback, never invented — a ceiling is a human decision under R-012.
   `FALLBACK_MAX_TOKENS` exists only for a model no role claims.
3. **No effort is sent at all.** Effort is orthogonal to attachment and cache
   capability, and inheriting a role's level across families could exceed a
   family ceiling (R-025) and inject a failure that says nothing about what
   this instrument measures. Pinned by a test.
4. **The pinned registry has no fallbacks.** A silent hand-off to another model
   would make the grid a liar about the row it sits in.
5. **REFUSED-by-design is driven by `supported_kinds_for`, not by naming xAI.**
   A kind the family never declared is refused and costs no call — xAI's pdf is
   the known case, and an adapterless family (mistral) declares nothing, so all
   three of its kinds refuse. Generalises to family five without an edit.

### Deviation from the packet's letter, flagged

The packet specifies `FAIL(first 80 chars of error)` **in the cell**. Built
literally, an 80-character cell sets the width of every column and the grid
stops being a grid — it rendered at 470 characters wide. The cell now carries a
numbered marker (`FAIL[1]`) and the full `FAIL(...)` text is listed in a
`failures (n):` block directly beneath the grid. Nothing is lost: the row's own
`cells` dict keeps the full string, and the artifact carries the footnotes.

Also unwrapped the router's error prefix. `route_call` reports "all models
failed for role 'matrix': tried X; last error: ...", and since the row already
names the model, the wrapper would spend the entire 80-character budget
repeating it. The cell now carries the provider's own words.

Sample render, all four cell types at once, from fakes:

```
model                                image              pdf                text               cache c1  cache c2  cost
openai/gpt-5.6-terra                 FAIL[1]            FAIL[2]            FAIL[3]            FAIL[4]   FAIL[5]   0.000000
anthropic/claude-haiku-4-5-20251001  OK                 OK                 OK                 64/0      64/0      0.006000
xai/grok-4.6                         OK                 REFUSED-by-design  OK                 64/0      64/0      0.004800
mistral/large                        REFUSED-by-design  REFUSED-by-design  REFUSED-by-design  64/0      64/0      0.002400
```

### Observed, never asserted

Cache cells are `cached/creation` per call, printed as measured (R-014). This
instrument **extends** the two open observations rather than settling them:
Gemini's zero hits and xAI's 128-token floor now get measured on every model
of their families rather than on one demo role each.

### Files

`smoke_matrix.py` (275, new), `smoke.py` (`--matrix` parsing, `MATRIX_PATH`,
`main(argv)`), `tests/test_smoke_matrix.py` (255, new),
`tests/test_smoke_wiring.py` (additive-mode guards). No registry edits, no
adapter changes, no new dependencies. `ledger/matrix-runs.md` is created by the
first real run, not by this build.

**Tests:** 217 passed, 0 failed — up from 200. Every file under the 300-line
ceiling. R-027 holds: the fixtures already satisfy the strictest known content
rules, so the sweep inherits the 32x32 image unchanged.

---

## Per-model live sweep — evidence report, no code change

**2026-08-18.** Investigation only; no source file was modified. Findings are
written up in full in **`ledger/model-evidence.md`**, with the one actionable
defect booked as **T-007**. `smoke.py` NOT run — every probe ran outside it with
human authorisation, writing to scratch meters so `ledger/meter.jsonl` still
carries only real smoke runs. Total spend ~$0.35.

**Why it was run:** attachments and caching had been live-proven on exactly one
model per family — each family's `demo_role_for` pick. `claude-fable-5` had never
made a metered call at all. The family adapters were proven; the models were not.

**Result: 8 of 9 registry models verified for all three attachment kinds and the
cache pair.** No adapter shape failed on any model. `claude-opus-5` is the sole
gap, and it is provider capacity — `overloaded_error` on five attempts over 25
minutes, failing identically streamed and blocking, with and without
attachments, while three sibling Anthropic models answered in the same minute.

**Four findings worth the ledger:**

1. **Gemini's cache was never broken — our prefix was too small, and the
   documented minimum is not sufficient.** Google documents 4,096 tokens for
   `gemini-3.7-flash`; measured, it does not engage until **between 5,682 and
   6,109**, and it commits only whole ~4,096-token blocks. A fix sized to the
   documented number would have gone green offline and cached nothing live —
   T-002's trap a second time, this time set by the vendor's own docs. Booked as
   T-007 with the cost tradeoff, since the block is shared by all four families.
2. **xAI's "128-token floor" is the block size, not a floor.** Every observed
   cached value across five prefix sizes is an exact multiple of 128 — 7 for 7.
   Commitment is asynchronous: one byte-identical pair went **backwards**, 2,560
   then 128, which a synchronous cache cannot do. Corrects R-027's wording.
3. **`max_tokens` must cover reasoning plus output.** At `max_tokens=32` Gemini
   returned 29 reasoning tokens and zero text with `finish_reason="length"`;
   sonnet-5 and fable-5 do the same at 8. A successful, correctly-metered call
   with nothing in it.
4. **The matrix cannot distinguish "failed" from "unavailable".** Opus-5's
   outage rendered as five `FAIL(...)` cells indistinguishable from a capability
   failure — a consequence of P-009.5's no-fallback pinning, which is correct;
   the rendering is what is ambiguous.

**Also recorded:** during the Opus-5 outage every `architect` call ran on
Sonnet-5 via the fallback chain, correctly and silently. A fallback substitution
is invisible unless you read `model_used` in the meter.

**Corrections requested of R-027** (xAI wording, Gemini threshold now measured)
are listed at the end of `model-evidence.md`.

**Tests:** unchanged at 217 passed — no source was touched.

---

## R-028 amendment — per-family cache blocks, UNAVAILABLE cells, fallback notices

**2026-08-18.** One amendment, four parts, applied on the Cortex rulings for the
per-model sweep. `smoke.py` and `--matrix` NOT run — the human runs those.

### 1. R-028 appended; R-027 corrected by measurement

xAI's "128-token floor" becomes **128-token blocks committed asynchronously**;
Gemini's "threshold unknown" becomes **5,682–6,109, whole ~4,096-token blocks,
position-independent, documented 4,096 necessary but not sufficient**. Both
corrections are measurements, not rewordings.

### 2. T-007: the shared cache block is retired

`CACHE_SYSTEM_BLOCK` **no longer exists**. `cache_block_for(family)` builds each
family's prefix from `_CACHE_PARAGRAPHS`, declared in `smoke_families.py` beside
the notes with the sizing evidence in the comment. The measured minimums live
beside them in `_CACHE_MINIMUMS`, and `smoke_debug.cache_minimum_for` delegates
there so family knowledge stays in one place.

| family | paragraphs | tokens | minimum | clears |
|---|---|---|---|---|
| anthropic | 60 | 3,721 | 2,048 | yes |
| openai | 60 | 3,721 | 1,024 | yes |
| xai | 60 | 3,721 | 128 | yes |
| gemini | 105 | 6,511 | 6,109 | yes |
| *undeclared* | 105 | 6,511 | 6,109 | falls back to the LARGEST |

**The guard is discriminating, demonstrated rather than asserted.** One test
proves every family's block clears its own minimum; a second proves the retired
60-paragraph size still clears anthropic, openai and xai **while falling below
gemini's** — so the guard cannot pass under the rule it replaced. A third asserts
`CACHE_SYSTEM_BLOCK` is absent by name, because a module-level constant with no
family at the call site is what made the undersizing invisible.

`prove_cache` also now prints the prefix-vs-minimum line for **every** family,
not only Anthropic. It previously printed that diagnostic solely for the one
family whose threshold we had already satisfied.

### 3. Matrix: UNAVAILABLE, one bounded retry, and fallback notices

`is_unavailable` matches **the provider's own words**, not the exception class —
LiteLLM wrapped the identical Opus-5 condition as `MidStreamFallbackError` when
streaming and `InternalServerError` when blocking. `_attempt` retries **once**
after `RETRY_DELAY_SECONDS` (20s, patched to 0 in tests) and records
`UNAVAILABLE` only if the second attempt also fails; a non-capacity error is
never retried and still renders as `FAIL(...)` with its footnote.

The discriminating half matters most here: a parametrised test asserts that
**three real defects we have actually hit** — T-004's MIME rejection, T-006's
image-dimension rejection, and the bad `grok-4.1-fast` model ID — are **not**
mistaken for outages. A matcher that called everything unavailable would hide
exactly the failures this grid exists to find.

`note_if_not_primary` prints `[fallback] <role>: <primary> did not answer —
<model> did` in all four prove phases, with a test proving it stays **silent**
when the primary answers.

### 4. T-007 marked RESOLVED referencing R-028.

### Flags for Cortex

1. **Dead duplicate deleted.** `smoke.py` carried its own unused copy of
   `_CACHE_PARAGRAPH` and `CACHE_SYSTEM_BLOCK`, orphaned by the P-005 split and
   referenced nowhere. Retiring the constant was the moment to remove it.
2. **Four R-017 splits in one amendment**, all at seams the code already marked:
   `smoke_matrix_render.py` (rendering) and `smoke_matrix_columns.py` (the shared
   column/verdict vocabulary, a leaf module so prober and renderer share it
   without a cycle); `tests/test_smoke_matrix_outage.py`; and
   `tests/test_smoke_fallback_notice.py`. Per R-026 each inherits its parent's
   map entries.

**Files:** `smoke_families.py` (190), `smoke_proves.py` (277), `smoke_matrix.py`
(262), `smoke_matrix_render.py` (78, new), `smoke_matrix_columns.py` (16, new),
`smoke_debug.py` (124), `smoke.py` (159), plus five test files. No registry
edits, no adapter changes, no new dependencies.

**Tests:** 238 passed, 0 failed — up from 217. Every file under the 300-line
ceiling.

---

## T-008 — the ping gate now tells an outage from a misconfiguration

**2026-08-18.** Applied on the ruling for T-008. `smoke.py` and `--matrix` NOT
run.

**What happened:** `smoke.py --matrix` pinged nine models, found eight healthy,
and refused to run anything — `PING FAILURES — fix registry.toml`. There was
nothing to fix. `anthropic/claude-opus-5` is a correct model ID that had
answered all day; Anthropic capacity was saturated.

**The instructive part:** this is the same defect R-028 had just corrected, one
layer earlier. `is_unavailable` was written for exactly this taxonomy and wired
into the matrix, which would have rendered Opus-5 as `UNAVAILABLE` — but it never
got the chance, because the gate returned 1 first. Fixing one instrument and
leaving the other untouched left the earlier and more damaging copy of the bug in
place. Worth remembering when a ruling corrects a class of error: the class
usually has more than one instance.

**Fix, per the ruling (option 1):**

- The capacity taxonomy moved out of `smoke_matrix.py` into a leaf module,
  `smoke_health.py`, so ping and matrix share **one** definition instead of
  agreeing by coincidence.
- `PingResult` gains `unavailable: bool`; the table prints `UNAVAIL … provider
  capacity, not config: …`.
- The gate blocks only on `not ok and not unavailable`. A config failure still
  prints "fix registry.toml" and runs nothing.
- `report_unavailable` warns loudly, naming each affected role and whether a
  reachable fallback covers it:

```
[warning] 1 model(s) unavailable (provider capacity, not config):
  anthropic/claude-opus-5
    primary for 'architect' — will run on anthropic/claude-sonnet-5
Proceeding. Affected cells record UNAVAILABLE.
```

**Guards, all discriminating.** A parametrised test asserts the trio — T-004's
MIME rejection, T-006's pixel floor, the bad `grok-4.1-fast` ID — all stay
`unavailable=False`, because a matcher generous enough to excuse them would wave
real defects through the gate. End to end: `main([])` returns **0** through a
synthetic outage with all four PROVE phases running, and still returns **1** on a
config failure with no phase running. And `report_unavailable` prints **nothing**
when every model answers.

### Flags for Cortex

1. **`tests/test_smoke_ping_gate.py` (new, R-017).** Both `test_smoke.py` (306)
   and `test_smoke_wiring.py` (350) crossed the ceiling; the T-008 block from
   each moved into one dedicated home rather than two.
2. **`smoke_health.py` (new, leaf).** Deliberately a leaf so the taxonomy has one
   owner. `smoke_matrix.py` re-exports `is_unavailable`, so existing imports and
   the R-028 tests are untouched.
3. **Unrelated observation, not fixed:** `test_adapters.py::test_transformation_
   keeps_text_documents_on_a_text_source` takes ~6s of the suite's 6.4s, a
   cold-cache cost inside LiteLLM's real transformation. Pre-existing, outside
   this ticket's scope, noted rather than touched.

**Files:** `smoke.py` (218), `smoke_health.py` (41, new), `smoke_matrix.py` (245),
`tests/test_smoke.py`, `tests/test_smoke_wiring.py`,
`tests/test_smoke_ping_gate.py` (new). No registry edits, no adapter changes, no
new dependencies.

**Tests:** 249 passed, 0 failed — up from 238. Every file under the 300-line
ceiling.

---

## FOUR-FAMILY BASELINE CERTIFICATE — signed 2026-08-18

**Human matrix run: `smoke.py --matrix`, 9 models, $0.24.** Four provider
families proven on the wire through one instrument.

### Gemini cache PROVEN LIVE — T-007 validated on the wire

**4,072 tokens cached — one block.** After 12 byte-identical calls that cached
nothing at the retired 3,721-token prefix, the per-family block ruled in R-028
(105 paragraphs, ~6,511 tokens) produced a hit on the first live run.

The number is the point. R-028 recorded the measured physics as *whole
~4,096-token blocks, each landing ~25 under a multiple* — 4,071 / 4,076 / 4,080
across the probe sweep. The live run returned **4,072**, inside that band. The
prediction held on hardware we had not tested it on, which is what turns a
measurement into a model.

Worth stating plainly what this vindicates: sizing to Google's **documented**
4,096 would have passed every offline test and cached nothing. The block was
sized to the **measured** 6,109 engagement point instead, and it worked. R-028's
"documented is necessary, not sufficient" is now proven, not merely observed.

### T-008's gate passed its first live outage

Its first exposure to the exact condition it was written for, one commit after
being written. `anthropic/claude-opus-5` pinged **UNAVAIL**, the run **proceeded**,
and **8 models were swept** where the old gate had blocked all nine with "fix
registry.toml" — advice that was wrong. The fallback was **named** rather than
silently substituted, so the operator could see which model actually answered.

Config failures still block. The taxonomy did its job in both directions on its
first live outing.

### Opus-5 — UNKNOWN due to outage

The row is **UNKNOWN-due-to-outage**, not FAIL: recorded honestly as
`UNAVAILABLE` rather than misread as a capability failure, which is precisely
the distinction R-028 and T-008 exist to draw. **Re-probe on provider recovery**
— `python sweep.py anthropic/claude-opus-5`, or simply the next matrix run.

This is the one gap in an otherwise complete baseline, and it is a provider
condition, not a defect.

### xAI 128-quantum confirmed again

The 128-token block size held once more on the live run — consistent with every
prior observation, all exact multiples of 128. R-028's correction of R-027 (a
quantum, not a floor) stands.

### Baseline status

| family | models | attachments | cache |
|---|---|---|---|
| anthropic | 4 | 3 of 4 proven | 3 of 4 proven |
| openai | 3 | 3 of 3 proven | 3 of 3 proven |
| gemini | 1 | proven | **proven live, first time** |
| xai | 1 | proven (pdf REFUSED by design) | proven |

**8 of 9 models certified.** The ninth is blocked by provider capacity and
carries an honest UNKNOWN.

---

## P-010 — Family Five: OpenRouter (aggregator)

**Built 2026-08-18.** Fully offline; `smoke.py` and `--matrix` NOT run.

### Contract 1 first: the R-023 seam, and it was broken

The packet mandated the seam test **before any adapter code**, and that ordering
paid for itself immediately — **the test failed against the shipped lookup.**

The priced lookup stripped exactly one prefix. An aggregator's strings carry
two, so `openrouter/anthropic/claude-opus-5` — an entirely ordinary thing for a
human to configure under R-012 — reached `anthropic/claude-opus-5`, missed, and
would have reported UNPRICED with `cost=None` on every receipt. Measured against
the real litellm 1.97.0 map: **568 cost-map entries were unreachable that way.**

Fixed with progressive stripping — full string first, then each stripped form,
first hit wins. Observed keying, recorded: OpenRouter models are keyed **with**
the full double prefix (97 such keys, all org-qualified), while many other models
are keyed bare. The map is inconsistent, which is exactly why the lookup must try
every form rather than assume a depth.

**The guard failed before it passed**, which is the only way to know it
discriminates. A companion test asserts the four certified families still
resolve, so the fix could not have been a widening that broke nothing visibly.

**All four P-010 target models are absent from the map entirely** — under every
form. They will render UNPRICED in ping, which is the warning working as
designed, and their receipts will read `cost=None` until the litellm pin moves.
Booked here as contract 1 requires.

### R-030 sweep: one member

Three prefix-splitting sites exist. `family_of` and `load_registry`'s error text
both take segment `[0]`, correctly `openrouter` for a double-prefixed string.
Only the cost lookup assumed a single prefix. **No siblings** — recorded so the
absence is a decision rather than an oversight.

### Contract 2: the adapter

Transformation entry point, recorded: `OpenrouterConfig.transform_request` in
`litellm/llms/openrouter/chat/transformation.py`, extending `OpenAIGPTConfig` and
directly usable, like xAI's and unlike Gemini's.

Every shape survives it — system, image, both text candidates, and PDF — because
OpenRouter validates no MIME type, the same reason T-004 slipped through on
OpenAI. **Fidelity could not decide, so docs did (R-024):**

- **PDF: built as the documented file part.** OpenRouter documents exactly
  `{"type": "file", "file": {"filename": ..., "file_data": "data:application/
  pdf;base64,..."}}`, which is what the transformation carries.
- **Text: the T-004 labelled frame.** OpenRouter's file docs cover PDFs and name
  no other format, so a `text/plain` file part would rely on an undocumented
  shape — the third family to reach this conclusion by the same route. A test
  pins that the rejected candidate **also** survives transformation, since that
  is what makes docs-as-authority load-bearing rather than decorative.
- **No cache marks.** The aggregator's upstream owns caching, and LiteLLM's
  OpenRouter transformation actively relocates `cache_control` into content for
  models that support it — all the more reason to place none.

**The adapter refuses nothing.** Unlike xAI, it declares all three kinds: on an
aggregator, capability is per-MODEL, so a family-wide refusal would be a guess.
Per-model acceptance is the matrix's verdict to report — that is what the grid
is for.

### Contract 3: R-031, recorded — the skip is an absence, not a special case

`OpenRouterAdapter` declares no `EFFORT_LEVELS`, so `effort_levels_for` returns
None and the existing R-025 guard has nothing to check. **Nothing in
`load_registry` names openrouter**, and a test asserts that by inspecting the
module source — a special case would have been a second thing to keep in step
with the first. Discriminating pair: an openrouter role loads at all five levels
while gemini still rejects `xhigh` and xai still rejects `max`.

### Redirect slugs: forbidden and enforced

`tests/test_no_redirect_slugs.py` scans every `.py`, `.toml`, `.md` and
`.example` in the repo plus the root `.env.example` — 45 files — for any quoted
`-latest` slug. It proves **its own reach** (registry.toml, smoke.py and
.env.example are in the scanned set) and **its own matcher** (it fires on
`kimi-latest` and stays silent on prose) before its silence is trusted.

### Contracts 4–7

Cache note pinned. OpenRouter is **deliberately absent** from `_CACHE_PARAGRAPHS`,
so R-028's fallback-to-largest rule applies — correct here, since upstream
minimums are unknowable in general. Usage extraction and streaming needed **zero
router changes**, asserted with openrouter-shaped fakes rather than assumed.
`.env.example` gains `OPENROUTER_API_KEY=`.

**Contract 6 held: the fifth family joined with zero structural changes.** The
existing iteration picked it up; only assertions were added.

### Flags for Cortex

1. **Four R-017 splits**, all at seams the code already marked:
   `adapters_openrouter.py` (the Dictionary names it),
   `tests/test_cost_map_seam.py`, `tests/test_registry_effort.py`, and
   `tests/test_no_redirect_slugs.py` as a new guard with no parent.
2. **`smoke_health.py` needed no change** despite being in the file map — the
   capacity taxonomy is provider-agnostic and already covers an aggregator's
   upstream errors. Listed rather than touched, per "do not fix what is outside
   your scope".

**Files:** `adapters.py` (296), `adapters_openrouter.py` (50, new),
`smoke_families.py` (196), `.env.example`, and eight test files. No registry
edits, no new dependencies, no keys.

**Tests:** 332 passed, 0 failed — up from 249. Every file under the 300-line
ceiling.

---

## R-023 seam confirmed and closed; R-031 and the UNPRICED note recorded

**2026-08-18.** Ledger record only; no source change. Full detail in the R-023
CONFIRMED entry in `ledger/rulings.md`.

**R-023's prediction was correct.** Its standing note asked that the stripping
lookup be verified on the double-prefixed OpenRouter family. It was, contract-1
first, and the seam was **broken**: single-prefix stripping left **568 real
cost-map entries unreachable**, each of which would have reported UNPRICED with
`cost=None` on every receipt.

**Fixed and pinned against observed keying**, which measurement shows is
inconsistent — **97 double-prefixed `openrouter/` keys** alongside **many bare
keys** — so no single stripping depth is correct. Progressive stripping, first
hit wins. The guard failed before it passed.

**R-031 recorded as implemented-by-absence**, asserted by source inspection:
nothing in `load_registry` names openrouter, and the skip exists only because
`OpenRouterAdapter` declares no vocabulary for the R-025 guard to check.

**Standing note recorded:** all four P-010 target models are absent from litellm
1.97.0's cost map under every form. UNPRICED by design until a pin revision
prices them; receipts carry tokens, `cost=None`. Token metering is unaffected —
only the dollar estimate is missing.

**Tests:** unchanged at 332 passed — no source was touched.

---

## Config: the OpenRouter seats — and the R-014 corollary they exposed

**2026-08-18.** Config edit under R-012, human-authorised. Not a packet build.

`judge_fifth` → `openrouter/moonshotai/kimi-k3` with
`openrouter/deepseek/deepseek-v4-pro-0813` as fallback; `floor_agent_third` →
`openrouter/deepseek/deepseek-v4-flash-0731`. Both at `effort = "high"`,
consistent with the standing minimum-effort policy. **11 roles, 5 families, 12
distinct models.** Comments record that effort here is unvalidated by design
(R-031) and that these models are UNPRICED.

### The edit broke a test, and the test was wrong

`test_the_real_cost_map_prices_every_shipped_model` asserted that **every**
shipped model is priced — under a docstring that read *"Structure, not values
(R-014) — the human may repoint any role."* The docstring was the tell: being
priced is a **value** of the human's config, not a structural property, and
R-012 lets the human route anywhere. These are the first UNPRICED models the
project has ever shipped, and a lawful registry edit turned the suite red.

**This is the R-014 corollary again** — config-independence must hold in every
dimension, not just the asserted one — and it is the second time a config edit
has exposed a test asserting a value it had no business asserting. The first was
the single-family assumption.

**Rewritten to assert what is genuinely structural:** for every shipped model and
fallback, `input_price_of` returns either None or a positive float — never zero,
negative, or garbage — and `is_priced` **agrees with it**. Coherence of the
lookup, not the contents of the map.

**The typo-catching value was not dropped, it was relocated.** A second test
asserts that whatever is unpriced is *reported* as unpriced by the ping table's
priced column — the surface a human is actually looking at. Neither the count nor
the identity of unpriced models is asserted, because both are the human's to
change.

### Confirmed after the edit

3 of 12 distinct models are unpriced, all openrouter, exactly as the standing
note predicts. Effort `"high"` loads clean on both seats without validation
(R-031) while gemini and xai ceilings still reject above theirs.

**Flag:** `test_cost_map_seam.py` now also owns the shipped-registry pricing
tests, moved there when `test_smoke_families.py` crossed the ceiling — the seam
file is the topic-correct home for "does the priced lookup answer correctly".

**Tests:** 333 passed, 0 failed. No source changed; one test corrected.

---

## FIVE-FAMILY ROSTER CERTIFICATE — signed 2026-08-18

**Human matrix run: `smoke.py --matrix`, 12 models, $0.31.** Five provider
families on one instrument.

### The Switchboard is COMPLETE

Gate, routing, meter, five families, caching, attachments, effort, streaming,
matrix — **all live-proven**. Every capability the Switchboard was specified to
have has been exercised against real providers, not only against fakes.

### Opus-5's row is complete — the outage is over

The gap the four-family certificate carried is closed. `anthropic/claude-opus-5`
now has a full row, and the honest UNKNOWN it carried was retired by
re-measurement rather than by assumption. T-008's `UNAVAILABLE` cell did exactly
its job in the interim: it held the place open instead of misreporting an outage
as a capability failure.

### Kimi K3 — multimodal confirmed live on all three kinds

`openrouter/moonshotai/kimi-k3` accepted image, PDF and text. **Upstream Moonshot
caching was observed engaging THROUGH OpenRouter — 6,718 cached on call 2.**

That is worth stating precisely, because the family note promises nothing:
*"aggregator — cache semantics belong to the routed upstream provider and may
vary per request with routing; reporting observed values."* The note is still
right. What we now know is that an upstream cache **can** reach us through the
aggregator, on this model, on this run. It remains an observation, not a
guarantee, because routing may differ next time.

### DeepSeek V4 Pro/Flash — image FAILs are MODEL EVIDENCE, not defects

Both DeepSeek rows failed on image and passed on PDF. That is not a defect at
any layer, and the asymmetry is the giveaway:

- OpenRouter's own catalog lists `input_modalities: ["text"]` for both
  `deepseek/deepseek-v4-pro-0813` and `deepseek/deepseek-v4-flash-0731`, against
  `["text","image","video"]` for `kimi-k3`. **They are text-only models** — the
  404/no-endpoints response is the upstream saying there is no vision path to
  route to, not OpenRouter withholding one.
- **PDF passes on the same models** because OpenRouter parses the file upstream
  and passes the parsed text, which a text-only model can read. An image has
  nowhere to go.

**Booked as model evidence, not defects.** This is precisely why
`OpenRouterAdapter` refuses nothing at the family level: a family-wide
`SUPPORTED_KINDS` would have to claim either that all OpenRouter models take
images (false for DeepSeek) or that none do (false for Kimi). Neither is
expressible as family knowledge, so the adapter sends and the grid reports per
model. Contrast xAI, where the whole family lacks document input and
`REFUSED-by-design` is correct.

### Roster status

| family | models | attachments | cache |
|---|---|---|---|
| anthropic | 4 | 4 of 4 | 4 of 4 |
| openai | 3 | 3 of 3 | 3 of 3 |
| gemini | 1 | proven | proven (T-007) |
| xai | 1 | proven (pdf REFUSED by design) | proven |
| openrouter | 3 | Kimi all three; DeepSeek text+pdf, image N/A by model | Moonshot upstream observed |

---

## Label honesty: an unpriced cost is not a zero cost

**Same class as the Gemini cache-note defect** — a label that misstates what we
know is worse than a missing one. There the run printed "unknown" about a family
we understood precisely; here it printed **`0.000000`** for a model nobody can
price. Zero claims the sweep was free. `None` means we do not know what it cost.
The three openrouter models this project ships are all unpriced in litellm
1.97.0, so the grid was asserting a falsehood on a quarter of its rows.

**Root cause:** two `cost_usd or 0.0` coercions in `smoke_matrix.py`, which
silently turned "unknown" into "free" before the cell was ever rendered.

**Fixed:** costs are collected as `float | None`. A row whose successful calls
include even one unknown renders `unpriced` — a total containing an unknown line
item is not a total. The summary line stops claiming to be the whole bill:
`Total cost: $0.006000 from 2 priced models; 1 unpriced, actual spend is higher`.

**The guards discriminate in both directions**, which matters because an
over-eager fix would have been just as dishonest:

- an unpriced call renders `unpriced`, never `0.000000`
- **a genuine `0.0` still renders `0.000000`** — a real zero is knowledge, not
  absence
- **REFUSED and UNAVAILABLE cells keep a true zero**: no call was made, so
  nothing was spent, and that zero must not be swept into "unpriced"
- one unknown among several known costs makes the whole row unknown
- the summary caveat appears only when something is actually unpriced

**Files:** `smoke_matrix.py`, `smoke_matrix_columns.py`, `smoke_matrix_render.py`,
`tests/test_smoke_matrix.py`, `tests/test_matrix_cost_labels.py` (new, R-017).

**Tests:** 340 passed, 0 failed — up from 333.

---

## P-011 — The Workspace: a project is a folder with a constitution

**Built 2026-08-19.** Fully offline. **No keys, no network, no smoke run** —
this packet needs none. The Switchboard is untouched, as specified.

The first post-Switchboard component, and the first top-level package besides
it: `workspace/`, with its own pyproject and the same pins discipline
(pydantic 2.11.7, pytest 8.4.1, hatchling 1.32.0 — nothing added).

### What was built

`create_project(slug, name, root)` stamps the Section 16.1 skeleton;
`open_project(slug_or_path, root)` validates it and hands back a typed handle.
Every Dictionary path is a property on `Project`, generated from the one layout
table in `skeleton.py` — **no department ever computes a path, and there is one
place to be right about layout, forever.**

### Dumb by design, asserted rather than promised

Two subprocess guards (the P-003 pattern): importing `workspace` pulls in
**neither litellm nor switchboard**. The second matters as much as the first —
`effective_registry_path` takes the global registry as a **parameter** precisely
so the Workspace never depends on the Switchboard.

The R-013 analogue is asserted **structurally**: a test walks the AST of every
module, finds every `os.environ` / `os.getenv` access, and checks each key is
`WORKSPACE_ROOT_ENV`. A text search was tried first and failed on a docstring
that merely used the words — and would also have been fooled by a variable
holding another variable's name, which is exactly what a guard must not be.

### Two ambiguities resolved, both recorded rather than resolved silently

1. **`signatures` is an ARRAY of tables, not a table keyed by status.** The
   Dictionary says "table"; contract 4 says "appends". The long-haul loop
   revisits states — `live → amended → building → … → live` — so a status-keyed
   table would overwrite the previous signing of `building` and lose exactly the
   history a signature chain exists to keep. Appending is the only reading that
   survives the documented lifecycle. A test signs `building` twice and asserts
   both survive.
2. **Every Dictionary path is created at birth EXCEPT `registry.toml`.** The
   test list says "every Dictionary path property exists after create"; contract
   1 says "does NOT create a project registry.toml (absence = inherit global)".
   Those conflict on exactly one entry, and the contract is explicit and
   reasoned, so it wins: `dictionary.toml`, `rulings.md`, `meter.jsonl` and
   `evidence.md` are stamped, `registry.toml` is not. An empty registry would
   not be a harmless placeholder — it would **override the global with nothing**.
   Pinned by name in `NEVER_CREATED` with a test.

### Transitions as a map, not an index

`live → amended → building` folds the lifecycle back on itself, so "the next one
along" cannot express it. `TRANSITIONS` is an explicit map, which also makes
`amended → deployed` illegal by simply not being present. A reachability test
walks the map and asserts every declared status is reachable from `draft` — an
unreachable state would be a lifecycle nobody can finish, and no single-
transition test would reveal it.

Only `draft → intent_signed` is gated today. **A test records that the others
are deliberately ungated**, so the day a department earns its gate, one
assertion has to be changed on purpose rather than discovered by surprise
(design doc 16.2 rule 4).

### The git law — applied and verified in this same commit

`projects/` added to the root `.gitignore`. Verified, not assumed:

```
$ git check-ignore -v projects/anything projects/probe/anything.txt
.gitignore:10:projects/   projects/anything
.gitignore:10:projects/   projects/probe/anything.txt
```

Kept as a **test** rather than a one-off manual check, with a discriminating
companion asserting the rule is not an over-broad ignore that would hide the
factory's own source (`workspace/src/workspace/factory.py` and
`switchboard/smoke.py` must NOT be ignored).

### Notes

- The packet cites "the Switchboard's 332"; it is **340** as of the matrix
  cost-label fix, which landed after P-011 was written. Both suites were run in
  full.
- `docs/foundry-design-document.md` was already at **v2.2** (Section 16 present
  and used as the authority here), so no replacement was needed. It remains
  untracked.

**Files:** `.gitignore`, `workspace/pyproject.toml`, `workspace/src/workspace/`
(`__init__.py` 22, `skeleton.py` 98, `project.py` 201, `factory.py` 155),
`workspace/tests/` (`test_create.py` 179, `test_open.py` 235,
`test_lifecycle.py` 234). Switchboard untouched.

**Tests: 413 passed, 0 failed — Switchboard 340 + Workspace 73.** Every file
under the 300-line ceiling.
