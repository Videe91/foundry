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
