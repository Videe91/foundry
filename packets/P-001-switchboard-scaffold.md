# Packet P-001 — Switchboard Scaffold

**Department:** Coding Floor
**Wave:** 0 (foundation)
**Language:** Python 3.12
**Architecture context:** The Switchboard is Foundry's LLM middleware (design doc §12.1). This packet builds ONLY the skeleton and the tagging gate — no LiteLLM integration yet, no real API calls. That comes in P-002.

## One job

Create the Switchboard package skeleton with the **mandatory tag gate**: a single entry function that accepts an LLM call request, validates its Foundry tags, and (for now) returns a stub response. The rule "no tags, no call" becomes real, executable code.

## Dictionary (use these exact names)

| Concept | Name |
|---|---|
| The call request object | `SwitchboardRequest` |
| The tag block | `CallTags` |
| The entry function | `route_call` |
| Tag validation error | `MissingTagsError` |
| The stub response | `SwitchboardResponse` |

Field names in `CallTags` (all snake_case):
`project_id`, `department`, `role`, `packet_id` (optional), `ticket_id` (optional), `attempt_number` (optional)

Allowed values for `department`: `intent`, `cortex`, `design_studio`, `floor`, `adversarial`, `deploy`, `post_deploy`

## Files to create (each under 300 lines)

```
switchboard/
├── pyproject.toml          — package definition, deps pinned below
├── src/switchboard/
│   ├── __init__.py         — exports route_call, SwitchboardRequest, CallTags
│   ├── tags.py             — CallTags model + validation + MissingTagsError
│   ├── request.py          — SwitchboardRequest + SwitchboardResponse models
│   └── router.py           — route_call: validates tags, returns stub response
└── tests/
    ├── test_tags.py
    └── test_router.py
```

## Pinned dependencies (install these EXACT versions, nothing else)

- `pydantic==2.11.7` (models + validation)
- `pytest==8.4.1` (dev dependency, tests only)

No other packages. Standard library for everything else.

## Behaviour contract

1. `route_call(request: SwitchboardRequest) -> SwitchboardResponse`
2. If any required tag is missing or empty → raise `MissingTagsError` naming exactly which tags are missing.
3. If `department` is not in the allowed list → raise `MissingTagsError` with the invalid value named.
4. Valid request → return `SwitchboardResponse` with `status="stub"`, echoing the tags back, plus a `received_at` UTC timestamp.
5. `CallTags` rejects unknown/extra fields (strict mode).

## Tests that must pass

- test: valid tags → route_call returns status "stub" and echoes all tags
- test: missing project_id → MissingTagsError, message contains "project_id"
- test: missing role → MissingTagsError, message contains "role"
- test: invalid department "marketing" → MissingTagsError, message contains "marketing"
- test: extra unknown field in tags → validation error
- test: optional fields (packet_id, ticket_id, attempt_number) may be omitted without error

## Forbidden

- No LiteLLM, no HTTP, no API keys, no network code — this packet is the gate only.
- No config files, no environment variable reading yet.
- No files outside the `switchboard/` directory.