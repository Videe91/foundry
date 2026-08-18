# Packet P-010 — Family Five: OpenRouter Adapter (Kimi + DeepSeek)

**Department:** Coding Floor
**Wave:** 9 (builds on the four-family baseline certificate, 2026-08-18)
**Language:** Python 3.12

**Architecture context (verified 2026-08-18):** OpenRouter is an AGGREGATOR — one OpenAI-compatible API fronting hundreds of models, routing each request to an upstream provider and load-balancing across them. That changes the physics: pricing varies by routed upstream, cache semantics belong to the upstream (Moonshot's cache-hit pricing exists; whether a given call hits it depends on routing), and capability varies per MODEL, not per family. Target models: `moonshotai/kimi-k3` (2.8T MoE, native multimodal, 1M ctx, ~$2.60–2.80/$13–14 — the slug is `moonshotai/`, never `moonshot/`; the wrong org prefix is the #1 cause of 404s), `moonshotai/kimi-k2.7-code` (coding specialist, $0.95/$4, $0.19 cache-hit), `deepseek/deepseek-v4-pro-0813` (GA, 1.05M ctx, ~$0.66/$1.98, documented effort vocab: high and xhigh, xhigh→max), `deepseek/deepseek-v4-flash-0731` (1.31M ctx, $0.078/$0.157 — cheapest capable brain anywhere). LiteLLM prefix: `openrouter/` + full slug → DOUBLE-PREFIXED model strings, e.g. `openrouter/moonshotai/kimi-k3`.

**Redirect slugs are FORBIDDEN everywhere** (fixtures, tests, comments, suggestions): `kimi-latest`, `deepseek-v4-flash-latest`, and any `-latest` pattern auto-redirect to whatever is newest — a silent model swap in production. Pinned explicit slugs only. (The gemini-2.5-pro lesson, inverted: there we dodged a deprecation; here we dodge an unrequested upgrade.)

Per R-012: no role→model prescriptions. Capability only.

## One job

An `OpenRouterAdapter` for `openrouter/`-prefixed models; the R-023 double-prefix cost-map seam tested and fixed if broken; effort validation ruled for an aggregator family; attachments in verified shapes; family-aware smoke coverage.

## Dictionary

| Concept | Name |
|---|---|
| The OpenRouter adapter | `OpenRouterAdapter` (adapters.py or `adapters_openrouter.py` per R-017/R-026 split pattern with re-export) |
| Family prefix routing | `adapter_for` extended: `"openrouter/"` → `OpenRouterAdapter` — matched BEFORE shorter prefixes if any ambiguity, and the family key for notes/blocks/demos is `openrouter` |

## Files to create or modify (each under 300 lines)

```
(project root)/.env.example — MODIFY: add OPENROUTER_API_KEY= placeholder
switchboard/
├── src/switchboard/adapters.py (± adapters_openrouter.py) — MODIFY/NEW
├── smoke_health.py / smoke_families.py — MODIFY per responsibilities (R-026: split files inherit parent map entries)
└── tests/
    ├── test_adapters_openrouter.py — NEW (R-017 pattern)
    └── test_smoke.py / test_smoke_wiring.py — MODIFY: fifth-family assertions
```

All other files stamped; R-016 flag with cited dumps for anything reality forces.

## Behaviour contract

1. **The R-023 seam — tested FIRST, before anything else is built.** The priced lookup strips one provider prefix; a double-prefixed string (`openrouter/moonshotai/kimi-k3`) stripped once leaves `moonshotai/kimi-k3`. Test offline against the REAL litellm 1.97.0 cost map: how are OpenRouter models actually keyed (with `openrouter/` prefix? bare slug? both?), and does our lookup find them? If broken: fix the lookup to try, in order, the full string, then each progressively-stripped form, first hit wins — pinned with a test citing the observed keying. If some target models are absent from the map entirely: they render UNPRICED in ping (the warning exists for exactly this), booked in the build log.
2. **Adapter shape:** OpenRouter is OpenAI-compatible, so the adapter starts from the OpenAI shapes: plain leading system message, no cache marks (aggregator — upstream owns caching), image as base64 data-URL part, text via BOTH candidates tested (R-025 booking: inline labelled frame vs text/plain file part), pdf per docs+transformation with the R-024 discipline — OpenRouter documents file/PDF handling via parsing plugins for many models, but acceptance is per-MODEL on an aggregator; if the transformation carries a file part, build it, and the matrix judges each model's real acceptance (that is what the grid is FOR). Every shape through LiteLLM's real openrouter transformation offline (entry point recorded, per the P-008/P-009 practice).
3. **Effort — new ruling for aggregator families, record as part of R-031:** an aggregator family has NO family-wide effort vocabulary — the vocabulary belongs to the ROUTED MODEL (DeepSeek V4 Pro documents high/xhigh; Kimi's is unpublished; hundreds of others vary). Therefore the `openrouter` family declares NO ceiling and load-time validation SKIPS it, exactly like a no-adapter family — with a registry-comment convention that effort compatibility on openrouter roles is the human's per-model responsibility (R-012), surfaced by ping/prove. The adapter still passes `reasoning_effort` through when set (OpenAI-compatible passthrough, transformation-verified). Guard: a test proving an openrouter role with ANY of our five effort values loads without validation error, and one proving anthropic/gemini validation is unchanged.
4. **Cache note (pinned per the label test):** "aggregator — cache semantics belong to the routed upstream provider and may vary per request with routing; reporting observed values." Cache demo block: undeclared family falls back to the largest block (existing R-028 rule) — correct here, since upstream minimums are unknowable in general.
5. **Usage/cost:** OpenAI-shaped usage expected; offline test with an openrouter-shaped fake (cited). Streaming: family-agnostic, one offline test.
6. **Smoke:** fifth family joins via existing iteration (zero structural changes expected — book it if not). Ping table must show the four target models' priced/unpriced status truthfully per contract 1's findings.
7. `.env.example` gains `OPENROUTER_API_KEY=`, placeholder only. R-013 unchanged.

## Tests that must pass (ALL offline)

test_adapters_openrouter.py:
- adapter_for("openrouter/moonshotai/kimi-k3") → OpenRouterAdapter; all four prior families unchanged; unknown → None
- R-022 checks through the real openrouter transformation (entry point recorded): system, image, winning text shape, and the pdf decision — content intact, cited
- no cache_control anywhere in the payload
- effort passthrough: openrouter-routed call carries reasoning_effort when set, omits when None

Registry/validation:
- openrouter role with each of the five effort values loads WITHOUT validation (aggregator skip, R-031); anthropic and gemini validation unchanged (discriminating pair)
- R-023 seam: priced lookup resolves double-prefixed strings per the observed cost-map keying (test against the real map, structure-not-values per R-014); absent models → priced=False

test_smoke.py / test_smoke_wiring.py:
- synthetic five-family registry → demos iterate five times; openrouter wiring assertions; cache note pinned; redirect-slug absence check: no `-latest` slug anywhere in fixtures or the shipped registry (grep-style test)

Full suite green, R-022 checks included.

## Forbidden

- Redirect slugs (`-latest`) anywhere.
- No role→model prescriptions (R-012); stamped files only as scoped (R-016 otherwise).
- No invented effort vocabulary for the aggregator; no invented attachment shapes.
- No OpenRouter-specific features (provider pinning, transforms, fallback routing options) — future packets if a department needs them.
- No new dependencies, no keys, no network in tests; only the human runs smoke/matrix.
