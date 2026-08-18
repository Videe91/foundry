# Packet P-004 — Family One: Anthropic Adapter (Caching + Attachments + First Light)

**Department:** Coding Floor
**Wave:** 3 (builds on P-003)
**Language:** Python 3.12
**Supersedes:** the earlier P-004 "First Light" packet, which was never built. Delete `packets/P-004-first-light.md` and record the supersession in the build log.

**Architecture context:** Design doc §12.1 promises per-model-family prompt adapters living in the Switchboard. This packet builds the adapter pattern and its first implementation: the Anthropic family — with prompt caching (design doc §12.2, cache-first doctrine), image + PDF attachments, `.env` key loading, and an Anthropic-only first-light smoke run. Families arrive one packet at a time: OpenAI, Gemini, xAI, OpenRouter follow in later packets. All model strings below are verified against Anthropic's official model documentation as of 2026-08-18.

## One job

Make every Anthropic-routed call flow through an Anthropic family adapter that (a) marks stable content for provider-side prompt caching, (b) converts image/PDF attachments into the provider's content format, and (c) records cache hits in the meter. Prove it with a real Anthropic-only smoke run.

## Cortex rulings applied

- **R-009:** this packet touches the test suite → create `switchboard/tests/conftest.py`, move the shared fakes there, `test_router.py` ends well under 300 lines. Coverage unchanged.
- **R-010:** `pyproject.toml` is modifiable → version becomes `0.4.0`.

## Dictionary (existing names unchanged; new names below)

| Concept | Name |
|---|---|
| One attachment | `Attachment` (fields: `kind: str` — allowed `"image"` or `"pdf"`; `path: str` — local file path) |
| Adapter interface | `FamilyAdapter` (protocol/base with one method: `prepare`) |
| The Anthropic adapter | `AnthropicAdapter` (file: `adapters.py`) |
| Adapter method | `prepare(system: str \| None, messages: list[Message], attachments: list[Attachment]) -> list[dict]` — returns provider-ready message dicts |
| Adapter selection | `adapter_for(model: str) -> FamilyAdapter \| None` (file: `adapters.py`) — `"anthropic/"` prefix → `AnthropicAdapter`; anything else → `None` (plain dict conversion, current P-002 behaviour) |
| Env loading helper | `load_env()` (file: `smoke.py`) — loads `.env` via python-dotenv |
| The smoke script | `smoke.py` (kept from the withdrawn packet's design: ping phase + prove phase) |

`SwitchboardRequest` gains: `system: str | None = None` (the stable, cacheable instruction block) and `attachments: list[Attachment] = []`.
`Usage` gains: `cached_tokens: int = 0` and `cache_creation_tokens: int = 0`.

## The new registry.toml (REPLACE entirely; R-004 header rule applies; Anthropic-only in this packet — other families join in their own packets)

**Standing rule (new, record in rulings as R-012): registry.toml is CONFIGURATION, not law.** The block below is the *default* mapping, not a prescription. The human may edit role→model assignments at any time without a packet, a build, or a stamp — that is the file's entire purpose. Code must never hardcode a model string; it only reads the registry. Packets after this one must not prescribe role→model choices; a future settings layer will manage this file. Roles may exist in the registry before any code uses them — presence in config is cheap, and it means the wiring is proven before the need arrives.

```toml
# Foundry Model Registry — role → model → fallback chain.
# THIS FILE IS USER CONFIGURATION. Edit freely; no packet or build required.
# Family status: Anthropic ACTIVE (P-004). OpenAI, Gemini, xAI, OpenRouter pending their packets.
# Model IDs verified against Anthropic's official docs, 2026-08-18.
# Env keys expected (via .env): ANTHROPIC_API_KEY

[roles.architect]
model = "anthropic/claude-opus-5"
fallbacks = ["anthropic/claude-sonnet-5"]
max_tokens = 128000

[roles.architect_max]
# Escalation tier for the deepest thinking moments. Present and wired, unused
# until Cortex can request it. Fable 5: highest capability, 2x Opus 5 price.
model = "anthropic/claude-fable-5"
fallbacks = ["anthropic/claude-opus-5"]
max_tokens = 128000

[roles.judge]
model = "anthropic/claude-sonnet-5"
fallbacks = ["anthropic/claude-haiku-4-5-20251001"]
max_tokens = 128000

[roles.floor_agent]
model = "anthropic/claude-haiku-4-5-20251001"
fallbacks = ["anthropic/claude-sonnet-5"]
max_tokens = 64000

[roles.default]
model = "anthropic/claude-haiku-4-5-20251001"
fallbacks = []
max_tokens = 64000
```

(Registry rationale, for the record: claude-opus-5 is Anthropic's documented recommendation for complex agentic work at $5/$25 per MTok; claude-sonnet-5 replaces the legacy sonnet-4-6 — newer AND cheaper at $2/$10 vs $3/$15; haiku-4-5 at $1/$5 is the floor. claude-fable-5 ($10/$50, "Slower" latency per the docs) is deliberately NOT a default chair: it is the escalation tier as `architect_max`, to be measured into regular use via the vital signs — cost per stamped packet, ticket rate — not defaulted in. **max_tokens policy: every role's value is its model's documented maximum output — 128k for Fable 5/Opus 5/Sonnet 5, 64k for Haiku 4.5 — because Anthropic's API requires the parameter, and setting it to the model's own maximum is the honest implementation of "no artificial limit." It is a ceiling, not a target: only generated tokens are billed. When a role's model is swapped (R-012), the human should also update max_tokens to the new model's documented maximum.** Cross-family fallbacks return when those families are integrated.)

**Contract addition — fallback ceilings:** when the fallback chain crosses to a model with a smaller documented maximum (e.g., Sonnet 5's 128k role falling back to Haiku's 64k), a max_tokens above the fallback model's limit would make the fallback call itself fail — turning a rescue into a second failure. Rule: the router clamps max_tokens per attempt to the smaller of the role's configured value and nothing else in this packet (a per-model maximum table is a future family-adapter concern); HOWEVER, if a fallback attempt fails with a provider error indicating max_tokens exceeds the model's limit, that error message flows into ProviderCallError like any other — visible, not masked. Registry authors (humans, per R-012) should keep fallback chains ceiling-compatible; the smoke ping table surfaces violations immediately since pings use max_tokens=8.

## Files to create or modify (each under 300 lines)

```
switchboard/
├── pyproject.toml          — MODIFY: version 0.4.0; add python-dotenv to a new [project.optional-dependencies] smoke group
├── registry.toml           — REPLACE: block above
├── .env.example            — NEW: `ANTHROPIC_API_KEY=` placeholder lines ONLY, no values ever
├── smoke.py                — NEW: load_env + ping phase + prove phase (Anthropic only)
├── src/switchboard/
│   ├── __init__.py         — MODIFY: also export Attachment, AnthropicAdapter, adapter_for
│   ├── adapters.py         — NEW: FamilyAdapter, AnthropicAdapter, adapter_for
│   ├── request.py          — MODIFY: system + attachments fields
│   ├── meter.py            — MODIFY: Usage gains cached_tokens, cache_creation_tokens (ge=0, default 0)
│   └── router.py           — MODIFY: adapter selection + usage extraction of cache fields
└── tests/
    ├── conftest.py         — NEW (R-009): shared fakes
    ├── test_router.py      — MODIFY: slimmed via conftest; new adapter-path tests
    ├── test_adapters.py    — NEW
    └── test_smoke.py       — NEW: offline tests for ping/prove logic
```

`tags.py`, `test_tags.py`, `registry.py`, `test_registry.py`, `test_meter.py` are FORBIDDEN to change. (`test_meter.py` already passes with default-0 new fields because pydantic defaults don't break existing constructions — if that assumption fails in practice, STOP and ticket, do not edit the stamped test.)

## Pinned dependencies

- `python-dotenv==1.2.3` (NEW, smoke extra only — the library itself never loads env)
- All existing pins unchanged. No other additions.

## Behaviour contract

1. **git hygiene first:** `.env` goes into `.gitignore` in the same commit that introduces `.env.example`. The real `.env` must never be committable.
2. **Adapter selection in route_call:** after role resolution, `adapter_for(model)`. If an adapter exists → messages come from `adapter.prepare(request.system, request.messages, request.attachments)`. If None → current P-002 plain-dict behaviour, and: a non-empty `system` is prepended as a plain `{"role": "system", ...}` message; non-empty `attachments` with no adapter → raise `ProviderCallError` stating attachments are unsupported for that model family (never silently drop a user's file).
3. **AnthropicAdapter.prepare — caching:** when `system` is provided, emit it as a system message whose content is a LIST of text blocks, the last block carrying `"cache_control": {"type": "ephemeral"}` (the LiteLLM-documented Anthropic shape). This makes the stable instruction block a cache prefix: first call writes the cache, subsequent calls within the TTL read it at a fraction of input price. Do NOT mark user messages — in Foundry's usage pattern the system/packet block is stable, the user turn changes.
4. **AnthropicAdapter.prepare — attachments:** each `Attachment` is read from disk and base64-encoded. `kind="image"` → an OpenAI-style image content part with a base64 data URL (media type inferred from extension: png/jpg/jpeg/webp/gif); `kind="pdf"` → a file content part with a base64 `data:application/pdf` data URL. Attachment parts are appended to the LAST user message's content (converted to list-of-parts form). Missing file → `FileNotFoundError` naming the path; unknown extension for an image → `ValueError` naming it.
5. **Usage extraction (router):** in addition to the three existing counts, read cache fields when present: `prompt_tokens_details.cached_tokens` → `cached_tokens`; the Anthropic-specific `cache_creation_input_tokens` → `cache_creation_tokens`. Absent → 0. Never a crash.
6. **Smoke — ping phase:** ping every unique model string in the registry (primaries + fallbacks, deduplicated) with a minimal real call (max_tokens=8). Print an OK/FAIL table with latency. ANY failure → print "PING FAILURES — fix registry.toml, then re-run", exit code 1, prove phase does NOT run.
7. **Smoke — prove phase (three real demonstrations):**
   a. **Roles:** one call per role through route_call, EXCLUDING `default` and `architect_max` (the escalation tier is pinged in phase one to prove the wiring, but not proven with a full call — no spending Fable 5 money on a status check), with a real MeterLedger on `ledger/meter.jsonl` (system: "Reply with exactly: FOUNDRY ONLINE", user: "Status?").
   b. **Cache:** call the same role TWICE with an identical, deliberately long system block (~1,500 words of fixed text built into smoke.py — long enough to clear Anthropic's minimum cacheable size). Print both calls' `cached_tokens` and `cache_creation_tokens`; the expected pattern (first call: cache_creation > 0; second call: cached > 0) is printed alongside actuals, clearly labeled, not asserted — network truth is reported, not assumed.
   c. **Attachments:** generate a tiny PNG (a few pixels, via a base64 constant embedded in smoke.py — no image library) and a tiny one-page PDF (minimal hand-written PDF bytes as a constant), save to a temp dir, send both to the floor_agent role asking "Name the two file types you received." Print the reply.
8. Smoke tags: `project_id="foundry-smoke"`, `department="adversarial"`, `role=<role being proven>`.
9. `load_env()` runs only in smoke.py's main path. Library code under `src/` must not import dotenv or read the environment.
10. Smoke prints must never include key values or environment variable contents.

## Tests that must pass (ALL offline — no network, no keys, no dotenv import in tests)

test_adapters.py:
- adapter_for("anthropic/claude-opus-5") → AnthropicAdapter; adapter_for("openai/gpt-5.2") → None
- prepare with a system string → first message is a system message, content is a list, last block has cache_control ephemeral
- prepare with no system → no system message emitted
- prepare with an image attachment (tmp_path PNG bytes) → last user message content is a list containing a base64 image part
- prepare with a pdf attachment → contains a base64 application/pdf part
- missing attachment file → FileNotFoundError naming the path
- unknown image extension → ValueError naming it

test_router.py (existing coverage preserved via conftest; add):
- anthropic-routed request with system + attachment → the fake completion_fn receives adapter-shaped messages (assert cache_control present and attachment part present)
- non-adapter model with attachments → ProviderCallError mentioning attachments
- non-adapter model with system → system arrives as a plain first message
- usage with prompt_tokens_details.cached_tokens=1920 and cache_creation_input_tokens=80 → Usage records both; absent → both 0

test_smoke.py:
- ping_model ok/fail behaviour (never raises); ping_registry deduplicates (assert fake call count)
- prove writes one meter record per non-default role with correct role tags (fakes only)

Full suite green.

## Forbidden

- No changes to the five stamped files listed above.
- No keys or key values anywhere in code, config, tests, output, or .env.example.
- No dotenv/env reading inside `src/`.
- No new dependencies beyond python-dotenv (smoke extra).
- Tests make zero network calls; only `python smoke.py`, run manually by a human, spends money.
- No image/PDF processing libraries — attachments are read as bytes and base64-encoded, nothing more.
