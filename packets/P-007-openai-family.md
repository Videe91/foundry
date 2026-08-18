# Packet P-007 — Family Two: OpenAI Adapter

**Department:** Coding Floor
**Wave:** 6 (builds on P-006; Anthropic family complete and live-proven including text attachments)
**Language:** Python 3.12
**Re-issues:** the superseded P-006 OpenAI draft, updated: text kind inherited, ping pricing check added, R-022 in force.

**Architecture context (verified against OpenAI's official docs 2026-08-18):** GPT-5.6 family (Sol/Terra/Luna) GA — ~1M context, 128k output; Sol $5/$30, Terra $2/$12, Luna $0.20/$1.20 per MTok. `reasoning.effort` accepts none/low/medium/high/xhigh/max — a superset of our levels; our `reasoning_effort` passthrough is OpenAI-native, zero refactor. Caching: cached reads ~90% off, writes billed 1.25x, engages on repeated prefixes ≥1024 tokens (recently reworked — the smoke demo REPORTS observed behaviour, never assumes). Pricing cliff: prompts >272k input tokens bill the whole request at 2x input/1.5x output.

Per R-012, this packet prescribes NO role→model choices. It builds capability; the human edits the registry.

## One job

An `OpenAIAdapter` so `openai/`-prefixed models get attachments (image + pdf + text) and clean system handling; cache visibility for OpenAI's usage shape; family-aware smoke demos; and a ping table that also reports whether each model is priced in the cost map.

## Dictionary (existing names unchanged; new names below)

| Concept | Name |
|---|---|
| The OpenAI adapter | `OpenAIAdapter` (file: `adapters.py`) |
| Family prefix routing | `adapter_for` extended: `"openai/"` → `OpenAIAdapter`; `"anthropic/"` → `AnthropicAdapter`; else None |
| Ping pricing check | `PingResult` gains `priced: bool` — whether the model exists in LiteLLM's cost map |

## Files to create or modify (each under 300 lines)

```
switchboard/
├── .env.example            — MODIFY: add OPENAI_API_KEY= placeholder
├── smoke.py                — MODIFY: family-aware demos + priced column in ping table
├── src/switchboard/
│   └── adapters.py         — MODIFY: OpenAIAdapter + adapter_for extension
└── tests/
    ├── test_adapters.py    — MODIFY: OpenAI adapter tests incl. R-022 transformation checks
    ├── test_smoke.py       — MODIFY: family-aware smoke logic tests
    └── test_smoke_wiring.py — MODIFY: per-family wiring assertions
```

All other files stamped. R-016 flag applies if reality forces more (cite the observed dump).

## Pinned dependencies

None added.

## Behaviour contract

1. **OpenAIAdapter.prepare — system:** a provided `system` string becomes a plain leading `{"role": "system", "content": <str>}` message. NO cache_control marks anywhere — OpenAI caching is provider-side on repeated prefixes.
2. **OpenAIAdapter.prepare — attachments, all three kinds:** identical loading rules (bytes, base64 for image/pdf, same errors). `kind="image"` → OpenAI image content part (base64 data URL). `kind="pdf"` → OpenAI file content part (base64 application/pdf data URL). `kind="text"` → whatever shape survives the R-022 transformation check for OpenAI: verify offline through LiteLLM's real OpenAI transformation which of (a) file part with text/plain data URL, or (b) inline text part, is accepted and preserves the content; build the accepted one, cite the verification in the build log. If neither round-trips cleanly, STOP and ticket — do not invent a third shape.
3. **R-022 gate:** every OpenAI payload shape this packet emits (system, image, pdf, text, cache-free messages) is run through LiteLLM's real OpenAI transformation offline; the fixtures assert the transformation-verified shapes and cite them. The suite is not green without these checks.
4. **Effort passthrough:** no code change expected — one offline test proving an `openai/`-routed call carries the role's effort as `reasoning_effort`. Our validated level set stays low/medium/high/xhigh/max ("none" widening is a future config-schema decision).
5. **Cache visibility:** OpenAI reports cached reads under `prompt_tokens_details.cached_tokens` — the path our extractor already reads. Expected: zero router changes; one offline test with an OpenAI-shaped usage fake (transformation/docs-cited per R-019) proving extraction. Reality disagreeing → R-016-flagged router fix with the dump cited.
6. **Streaming:** family-agnostic already; one offline test that a streamed `openai/`-routed call meters from the terminal usage chunk.
7. **Ping pricing check:** ping_model also checks the model string against LiteLLM's cost map; the table prints `OK (priced)` / `OK (UNPRICED — update litellm pin)` / `FAIL`. Unpriced is a warning, not a gate — the call works, the receipt would read cost=None, and the human decides. Offline test: a fake model string absent from the cost map → priced=False.
8. **Smoke — per-family demos:** cache and attachment demos run once per family present in the registry (families = unique prefixes among role primaries), cheapest-max_tokens role of each family. Cache demo per family keeps the byte-identical two-call pattern; for OpenAI it prints observed cached_tokens with the honest label "reads discounted on repeated prefix ≥1024 tokens; recently reworked — reporting observed values." Attachments demo per family sends PNG + PDF + .md and asks the model to name all three; families without an adapter are skipped with a printed note.
9. **.env.example** gains `OPENAI_API_KEY=`, placeholder only. R-013 unchanged.

## Tests that must pass (ALL offline)

test_adapters.py additions:
- adapter_for("openai/gpt-5.6-terra") → OpenAIAdapter; anthropic unchanged; unknown → None
- system becomes plain leading system message; NO cache_control anywhere in the payload (transformation-checked)
- image, pdf, and text parts in transformation-verified OpenAI shapes on the last user message; same FileNotFoundError/ValueError behaviour
- R-022 checks: each emitted shape survives LiteLLM's real OpenAI transformation with content intact

test_smoke.py / test_smoke_wiring.py:
- per-family demo iteration on a synthetic two-family registry (invoked once per family; byte-identical cache pair per family; assert via fakes)
- attachments demo skips an adapterless family with the note, no crash
- ping priced column: absent-from-cost-map model → priced=False, table renders the warning
- wiring guard: per-family assertions that system/attachments(3 kinds)/effort/stream options/meter pass through

test_router.py or test_cache.py (R-018 pre-auth: if test_router.py must grow, create tests/test_cache.py and move cache tests there):
- OpenAI-shaped usage fake → cached_tokens extracted; effort on openai/ route; streamed openai/ call meters

Full suite green, R-022 checks included.

## Forbidden

- No role→model prescriptions (R-012).
- No changes to stamped files beyond listed scope; R-016 flag for anything reality forces.
- No new dependencies, no keys, no network in tests; only the human runs smoke.py.
- No Responses-API migration, no tool-calling, no "none" effort widening, no citations/Files API (R-021).
