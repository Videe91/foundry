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
