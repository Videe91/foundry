# Packet P-002 — Switchboard Routing: LiteLLM + Model Registry

**Department:** Coding Floor
**Wave:** 1 (builds on P-001)
**Language:** Python 3.12
**Architecture context:** Design doc §12.1. P-001 built the tag gate. P-002 makes the Switchboard actually route calls to real models via LiteLLM, driven by a role-based model registry. Cost metering is NOT this packet (P-003).

## One job

After the tag gate passes, resolve the caller's `role` to a model (with fallbacks) via a TOML registry, execute the call through LiteLLM, and return the model's answer. Tests run fully offline via an injected fake caller.

## Resolves from P-001 review (Cortex rulings)

- **Ticket 2 resolution:** `SwitchboardRequest.prompt` is REPLACED by `messages` (see Dictionary). Remove `prompt` entirely.
- **Ticket 3 resolution:** `pyproject.toml` gains a `[build-system]` with the pinned backend below. The package must become installable (`pip install -e .` works).

## Dictionary (use these exact names; P-001 names remain unchanged)

| Concept | Name |
|---|---|
| One chat message | `Message` (fields: `role`, `content`, both `str`) |
| The registry (parsed) | `ModelRegistry` |
| One role's entry | `RoleRoute` (fields: `model: str`, `fallbacks: list[str]`, `max_tokens: int`) |
| Registry loader | `load_registry(path) -> ModelRegistry` |
| Role lookup failure | `UnknownRoleError` |
| All models failed | `ProviderCallError` |
| The real/injected caller | `completion_fn` (parameter on `route_call`) |
| Registry file | `registry.toml` (repo path: `switchboard/registry.toml`) |

`Message.role` allowed values: `system`, `user`, `assistant`.
`SwitchboardResponse` gains fields: `model_used: str`, `content: str`. `status` becomes `"ok"` for real calls (`"stub"` no longer used).

## Files to create or modify (each under 300 lines)

```
switchboard/
├── pyproject.toml          — MODIFY: add [build-system], add litellm dep
├── registry.toml           — NEW: the model registry config
├── src/switchboard/
│   ├── __init__.py         — MODIFY: also export load_registry, Message, errors
│   ├── request.py          — MODIFY: prompt → messages: list[Message]; response fields
│   ├── registry.py         — NEW: RoleRoute, ModelRegistry, load_registry, UnknownRoleError
│   └── router.py           — MODIFY: registry resolution + LiteLLM call + fallbacks
└── tests/
    ├── test_registry.py    — NEW
    └── test_router.py      — MODIFY: offline tests with fake completion_fn
```

`tags.py` and `test_tags.py` are FORBIDDEN to change — the gate is stamped.

## Pinned dependencies (EXACT versions, verified on PyPI 2026-08-18)

Runtime:
- `pydantic==2.11.7` (unchanged)
- `litellm==1.97.0` (NEW)

Dev:
- `pytest==8.4.1` (unchanged)

Build system (Ticket 3 fix):
- `hatchling==1.32.0` — `[build-system] requires = ["hatchling==1.32.0"], build-backend = "hatchling.build"`

Registry file format is TOML read via the standard library `tomllib` — NO pyyaml, NO extra parser dependency.

## registry.toml contents (create exactly this)

```toml
# Foundry Model Registry — role → model → fallback chain.
# Swapping any brain in the factory = editing one line here.

[roles.architect]
model = "anthropic/claude-sonnet-4-6"
fallbacks = ["openai/gpt-4o"]
max_tokens = 4096

[roles.judge]
model = "openai/gpt-4o"
fallbacks = ["anthropic/claude-sonnet-4-6"]
max_tokens = 2048

[roles.floor_agent]
model = "anthropic/claude-haiku-4-5-20251001"
fallbacks = ["openai/gpt-4o-mini"]
max_tokens = 4096

[roles.default]
model = "anthropic/claude-haiku-4-5-20251001"
fallbacks = []
max_tokens = 1024
```

## Behaviour contract

1. `route_call(request, registry, completion_fn=None) -> SwitchboardResponse`. When `completion_fn` is None, use `litellm.completion`. The tag gate from P-001 runs FIRST, unchanged.
2. Role resolution: look up `request.tags.role` in the registry. Not found → fall back to the `default` role entry. If `default` is also absent from the file → raise `UnknownRoleError` naming the role.
3. The call: invoke `completion_fn(model=..., messages=..., max_tokens=...)` with messages converted to plain dicts (`[{"role": ..., "content": ...}]`).
4. Fallback chain: if the call raises ANY exception, try the next model in `fallbacks`, in order. All exhausted → raise `ProviderCallError` listing every model tried and the final error message.
5. Success: return `SwitchboardResponse` with `status="ok"`, `model_used` = the model that actually answered, `content` = the answer text (`response.choices[0].message.content` shape — the fake in tests must mimic this shape), tags echoed, `received_at` timestamp as before.
6. `load_registry`: parse the TOML file; malformed structure (missing `model` field, non-list `fallbacks`) → raise `ValueError` naming the bad role. Empty/missing file → `FileNotFoundError` passes through naturally.
7. API keys come ONLY from environment variables (LiteLLM's native behavior — provider keys like `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). The code never reads, stores, or logs a key. No key handling code at all.
8. Messages list must be non-empty; empty → pydantic validation error (min length 1 on the field).

## Tests that must pass (ALL offline — no network, no real keys)

test_registry.py:
- valid registry.toml parses; architect resolves to its model and fallbacks
- unknown role resolves to default entry
- unknown role with no default entry in file → UnknownRoleError naming the role
- malformed entry (missing `model`) → ValueError naming the role

test_router.py (keep all P-001 gate tests passing, adapted to `messages`):
- valid call with fake completion_fn → status "ok", model_used = primary model, content = fake's answer
- primary model's fake raises → fallback model used, model_used = fallback
- all models raise → ProviderCallError, message names every model tried
- tag gate still fires first: missing project_id → MissingTagsError, fake completion_fn NEVER called (assert call count 0)
- empty messages list → validation error
- fake completion_fn receives messages as plain dicts and the role's max_tokens

## Forbidden

- No changes to tags.py or test_tags.py.
- No network calls in tests. The fake completion_fn is a plain function/object in the test file — no mocking libraries beyond the standard library.
- No API keys anywhere in code, config, or tests.
- No cost/token tracking — that is P-003.
- No files outside `switchboard/` and `ledger/`.
- No streaming, no async — synchronous calls only in this packet.
