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
