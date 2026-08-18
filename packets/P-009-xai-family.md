# Packet P-009 — Family Four: xAI (Grok) Adapter

**Department:** Coding Floor
**Wave:** 8 (builds on P-008; three families live-proven, $0.022 total)
**Language:** Python 3.12

**Architecture context (verified 2026-08-18 against xAI docs/release notes):** Grok 4.6 is the flagship (released 2026-08-12) — $2/$6 per MTok, $0.50 cached input, 500K context, text+image input, effort low/medium/high (default high) plus xhigh. Grok 4.5 supports only low/medium/high (and is EU-restricted on the API console). Grok 4.1 Fast is the volume tier — $0.20/$0.50 with a 2M context. Long-context cliff: >200K input tokens doubles rates. The API is OpenAI-compatible; LiteLLM prefix `xai/`. Notable: xAI returns `cost_in_usd_ticks` in usage — the provider's exact billed cost.

**The prediction's inverse case:** xAI documents text+image input only — possibly NO document/file part at all. The transformation check and docs decide; the live run confirms.

Per R-012: no role→model prescriptions. Capability only.

## One job

A `GrokAdapter` for `xai/`-prefixed models: image + text attachments in their verified shapes, an honest refusal for PDFs if the family genuinely lacks a document part, effort within the family's safe vocabulary, and family-aware smoke coverage.

## Dictionary

| Concept | Name |
|---|---|
| The xAI adapter | `GrokAdapter` (file: `adapters.py`; `adapters_xai.py` pre-authorized per R-017 if the ceiling forces it, with re-export) |
| Family prefix routing | `adapter_for` extended: `"xai/"` → `GrokAdapter` |

## Files to create or modify (each under 300 lines)

```
(project root)/.env.example — MODIFY: add XAI_API_KEY= placeholder
switchboard/
├── src/switchboard/adapters.py (± adapters_xai.py) — MODIFY/NEW
└── tests/
    ├── test_adapters_xai.py — NEW (R-017 pattern)
    └── test_smoke.py / test_smoke_wiring.py — MODIFY: fourth-family assertions
```

All other files stamped; R-016 flag with cited dumps for anything reality forces. Smoke's family iteration should again need zero structural changes.

## Pinned dependencies

None added.

## Behaviour contract

1. **System:** plain leading system message. Caching is provider-side on xAI (cached-input pricing exists); no marks. The family's cache note in `_CACHE_NOTES` (pinned per the P-008 label test): "provider-side cached input pricing; no client marks — reporting observed values."
2. **Attachments — image:** OpenAI-compatible image part (base64 data URL), transformation-verified (R-022; find xAI's real transformation entry point and record it, as done for Gemini).
3. **Attachments — text:** test both candidates per the R-025 booking (inline text/plain part vs the T-004 labelled frame). Build what fidelity + docs acceptance support; docs are the acceptance authority (R-024). Record which candidate won and why.
4. **Attachments — pdf, the inverse case:** if docs confirm no document part exists for xAI chat input, the adapter REFUSES `kind="pdf"` loudly — raising the same error style as the no-adapter path, message naming the kind, the family, and that the family's API accepts text+image only. Never silently dropped, never smuggled as an image. If a document part DOES exist (docs or transformation reveal one), build it transformation-verified and note the finding. The build log records the outcome against the registered pattern.
5. **Effort — family vocabulary per R-025:** declare the xai ceiling as **low/medium/high** — the intersection safe across ALL current Grok models — even though 4.6 accepts xhigh. Reasoning, recorded: R-025 validates per-family at load; effort vocabularies differing per-model WITHIN a family is a new wrinkle, and declaring the superset would let a lawful config (4.5 + xhigh) explode at call time — the exact failure R-025 exists to prevent. The intersection protects; a 4.6 user temporarily loses xhigh. Book the refinement as a future ruling candidate: per-model effort vocabularies, only if a real workload wants xhigh on 4.6.
6. **Cost — the ticks question:** check offline whether LiteLLM surfaces `cost_in_usd_ticks` (or a translation of it) in the usage object for xai models. If yes: capture it into the meter as the authoritative `cost_usd` for xai calls (provider-exact beats map-estimate), pinned by a test with the observed shape cited. If LiteLLM drops it: book as an R-024 note — the live run's debug dump settles what actually arrives, and a future amendment captures it if present. Do not build speculative parsing for a field never observed.
7. **Usage/cache extraction:** expected zero router changes (OpenAI-compatible shape); offline test with an xai-shaped usage fake, transformation/docs-cited.
8. **Streaming:** family-agnostic; one offline test.
9. **Registry-adjacent notes for the human (comments only, no prescriptions):** the 200K long-context price cliff; 4.5's EU restriction; 4.1 Fast's 2M window at volume pricing.
10. `.env.example` gains `XAI_API_KEY=`, placeholder only. R-013 unchanged.

## Tests that must pass (ALL offline)

test_adapters_xai.py:
- adapter_for("xai/grok-4.6") → GrokAdapter; other families unchanged
- R-022 checks through xAI's real transformation (entry point recorded): system, image, and the winning text shape survive with content intact
- pdf refusal (or the built document part if one exists): loud, naming kind/family/reason
- effort ceiling: synthetic registry with an xai-primary role at "xhigh" fails AT LOAD naming role/family/ceiling; same registry passes at "high" (the discriminating pair, per R-025's precedent)

test_smoke.py / test_smoke_wiring.py:
- synthetic four-family registry → demos iterate four times; xai wiring assertions (system/attachments-2-or-3-kinds/effort/stream/meter); the pdf-refusing family's attachments demo behaviour: sends only the kinds the family accepts and prints a note for the refused kind (never a crash — mirror the adapterless-family skip pattern)
- cache note pinned: xai gets its real note, not the fallback

test_cache.py / test_meter.py-adjacent (topic-correct homes per R-023):
- ticks capture pinned IF built (contract 6), with the observed shape cited

Full suite green, R-022 checks included.

## Forbidden

- No role→model prescriptions (R-012); stamped files only as scoped (R-016 otherwise).
- No superset effort vocabulary (contract 5's reasoning is the law for this packet).
- No speculative ticks parsing without an observed shape.
- No PDFs smuggled as images; no invented attachment shapes.
- No new dependencies, no keys, no network in tests; only the human runs smoke.py.
- No xAI tools/search/video/voice — future packets if ever needed.
