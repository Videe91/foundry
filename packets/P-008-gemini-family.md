# Packet P-008 — Family Three: Gemini Adapter

**Department:** Coding Floor
**Wave:** 7 (builds on P-007; two families live-proven)
**Language:** Python 3.12

**Architecture context (verified against ai.google.dev, 2026-08-18):** Gemini 3.7 Flash is current — 1M context, 64k output, intro $0.75/$3.75 per MTok through 2026-12-31 (then $1.50/$7.50); Gemini 3.1 Pro in preview for heavier work. **Gemini 2.5 Pro shuts down 2026-10-16 — it must not appear in any suggestion, fixture, or comment.** Thinking is `thinking_level` with three values (low/medium/high) vs our five effort levels. Gemini 3.6+ removed temperature/top_p/top_k as accepted parameters. Both implicit caching and explicit context caching exist; LiteLLM documents Anthropic-style `cache_control` as working for Gemini.

**Registered prediction under test (R-024):** "document/file parts are PDF-only; text travels as text" — observed on Anthropic (T-003) and OpenAI (T-004). Gemini's natively multimodal inline parts may accept text/plain directly, breaking the pattern. The transformation check plus provider docs decide the build shape; the live run decides the truth; the build log records whether the prediction held.

Per R-012: no role→model prescriptions. Capability only; the human edits the registry.

## One job

A `GeminiAdapter` for `gemini/`-prefixed models: attachments (image + pdf + text), system handling, cache marking per LiteLLM's documented Gemini support, effort-level translation verified rather than assumed — proven by the family-aware smoke run.

## Dictionary

| Concept | Name |
|---|---|
| The Gemini adapter | `GeminiAdapter` (file: `adapters.py`; if the 300 ceiling forces it, `adapters_gemini.py` is pre-authorized per R-017, with `adapters.py` re-exporting so `adapter_for` and the public surface are unchanged) |
| Family prefix routing | `adapter_for` extended: `"gemini/"` → `GeminiAdapter` |

## Files to create or modify (each under 300 lines)

```
(project root)/.env.example  — MODIFY: add GEMINI_API_KEY= placeholder (root file, per P-004 amendment / R-023)
switchboard/
├── src/switchboard/adapters.py (± adapters_gemini.py) — MODIFY/NEW
└── tests/
    ├── test_adapters_gemini.py — NEW (R-017 pattern from the OpenAI split)
    ├── test_smoke.py / test_smoke_wiring.py — MODIFY: third-family assertions
```

All other files stamped; R-016 flag with cited dumps for anything reality forces. Smoke's family iteration should need ZERO changes — that is the point of the per-family design; if it does need changes, that is a finding worth its own build-log sentence.

## Pinned dependencies

None added.

## Behaviour contract

1. **System + cache:** system string as a leading system message; the stable block carries the Anthropic-style `cache_control: {"type": "ephemeral"}` mark per LiteLLM's documented Gemini support. R-022 fidelity check: the mark must survive LiteLLM's real Gemini transformation into whatever Gemini-side representation it maps to; if the transformation drops it silently, build WITHOUT marks (implicit caching only), record the finding, and the cache demo's label says "implicit caching only; explicit marks not supported via this path."
2. **Attachments — the prediction test:** run all three kinds through LiteLLM's real Gemini transformation offline. Image and pdf: base64 inline shapes per the transformation's accepted form. Text: test BOTH candidates — (a) a text/plain inline-data part, (b) the labelled inline text frame from T-004 (same fixed frame format, pinned). Build whichever the transformation carries faithfully AND provider docs accept (R-024: docs are the acceptance authority where the transformation doesn't validate); prefer (a) if both stand, since it preserves document semantics. Record in the build log whether the registered prediction held or broke for Gemini.
3. **Effort translation — verified, not assumed:** run a `gemini/`-routed request with each of our five effort values through the real transformation and observe what LiteLLM emits (thinking_level? thinking budget? dropped?). Contract: our five values must land as a sensible monotone mapping onto Gemini's low/medium/high (docs authority: three levels). If LiteLLM maps xhigh/max to high (or equivalent), pin it with tests and record the observed mapping. If LiteLLM DROPS or mistranslates any value such that the provider would reject or silently ignore it, STOP and ticket with the dumps — do not invent a client-side mapping without a ruling.
4. **No forbidden parameters:** the transformation check asserts the outgoing Gemini payload contains no temperature/top_p/top_k (removed in Gemini 3.6+) — neither from us nor injected by LiteLLM defaults.
5. **Usage + cost:** expected zero router changes; offline test with a Gemini-shaped usage fake (transformation/docs-cited) proving token and cached-token extraction; priced column works via the existing prefix-stripping lookup (the R-023 seam — verify `gemini-3.7-flash` keys correctly, and record how).
6. **Streaming:** family-agnostic; one offline test that a streamed `gemini/`-routed call meters from terminal usage.
7. **Smoke:** no structural changes expected. The third family joins the ping table, per-family cache demo (with the honest label from contract 1's outcome), and the three-file attachments demo automatically via the existing iteration.
8. `.env.example` gains `GEMINI_API_KEY=`, placeholder only. R-013 unchanged.

## Tests that must pass (ALL offline)

test_adapters_gemini.py:
- adapter_for("gemini/gemini-3.7-flash") → GeminiAdapter; other families unchanged; unknown → None
- R-022 checks: every emitted shape survives the real Gemini transformation with content intact; cache mark survival (or its documented absence per contract 1); no temperature/top_p/top_k in the outgoing payload
- three attachment kinds in their transformation-verified shapes; same FileNotFoundError/ValueError behaviour; the chosen text shape pinned with the prediction outcome cited
- effort: five values → observed mapping pinned (or the ticket path taken)

test_smoke.py / test_smoke_wiring.py:
- synthetic three-family registry → demos iterate three times; wiring assertions cover the gemini family (system/attachments/effort/stream/meter pass-through)

Full suite green, R-022 checks included.

## Forbidden

- gemini-2.5-pro anywhere (deprecated 2026-10-16).
- No role→model prescriptions (R-012); no changes to stamped files beyond scope (R-016 flag otherwise).
- No new dependencies, no keys, no network in tests; only the human runs smoke.py.
- No client-side effort mapping without a ruling; no invented attachment shapes (both candidates are named; a third needs a ticket).
- No Gemini tools (Search/Code Execution/etc.), no Interactions API, no explicit context-caching API — future packets when a department needs them.
