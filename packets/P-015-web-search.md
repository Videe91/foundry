# Packet P-015 — The Switchboard Learns to Search (Anthropic Family First)

**Department:** Coding Floor
**Wave:** 14 (builds on P-014 + T-009 fix; Switchboard 350 + Workspace 92 + Intent 53 + CLI 85, all stamped)
**Language:** Python 3.12

**Architecture context (verified against Anthropic docs + LiteLLM, 2026-08-19):** Anthropic's web search is a SERVER-SIDE tool — declared in the request's `tools` array as `{"type": "web_search_20250305", "name": "web_search", "max_uses": N}` (optionally `allowed_domains` XOR `blocked_domains`, `user_location`); the model decides when to search within the turn; results and citations return as content blocks in the same round trip. Pricing is dual: $10 per 1,000 searches PLUS search results billed as input tokens (a single search can add thousands). The stable `web_search_20250305` works across model generations; `web_search_20260209` (dynamic filtering) is booked as a future upgrade, not built. Consumers: P-016 wires it to the interviewer (mid-conversation lookups) and a researcher role (the sweep). This packet is capability only.

**Family law applies:** search is family knowledge. Only the Anthropic family gains it here; a search-enabled request routed to any other family refuses loudly (the attachments-before-adapters pattern). Other families join in their own amendments, docs-first.

## One job

`SwitchboardRequest` gains an optional `web_search` spec; the Anthropic adapter renders it into the provider tool block; usage extraction captures the search count; the meter's receipts carry it; smoke proves it live with one real searched answer.

## Dictionary

| Concept | Name |
|---|---|
| The spec | `WebSearchSpec` (file `request.py`; fields: `max_uses: int = 5` (ge=1, le=20), `allowed_domains: list[str] = []`, `blocked_domains: list[str] = []`, `user_location: dict \| None = None`) |
| Request field | `SwitchboardRequest.web_search: WebSearchSpec \| None = None` |
| Adapter hook | `AnthropicAdapter.search_tool(spec) -> dict` — renders the `web_search_20250305` block |
| Family gate | a search-enabled request to a family whose adapter lacks `search_tool` → `ProviderCallError` naming the family and that web search is unsupported there |
| Usage fields | `Usage.web_search_requests: int = 0` — extracted from the response usage's server-tool section (exact path discovered per R-022/R-019, cited) |
| Meter | `MeterRecord` carries `web_search_requests` (default 0) — receipts show searches alongside tokens |
| Smoke | prove 5: `prove_search` — one live searched call on the Anthropic family's demo role |

## Files to create or modify (each under 300 lines)

```
switchboard/
├── src/switchboard/
│   ├── request.py          — MODIFY (R-016 flag: stamped; one-amendment unstamping): WebSearchSpec + field
│   ├── adapters.py         — MODIFY: AnthropicAdapter.search_tool; family gate wiring
│   ├── router.py           — MODIFY (R-016 flag): pass tools when spec present; usage extraction
│   └── meter.py            — MODIFY (R-016 flag): web_search_requests on Usage + MeterRecord
├── smoke_proves.py         — MODIFY (R-026 inheritance): prove_search
└── tests/
    ├── test_search.py      — NEW (R-017 pattern)
    └── existing homes      — MODIFY only where topic-correct (R-023 precedent)
```

Workspace, intent, foundry_cli: untouched. Registry: NO role changes (P-016 decides which roles may search — that is config plus consumer wiring, not this packet).

## Behaviour contract

1. **Spec validation at the model:** pydantic-enforced ranges; `allowed_domains` and `blocked_domains` mutually exclusive (docs law: one or the other, never both) — violation raises at construction naming both fields.
2. **Rendering (R-022):** `search_tool(spec)` emits exactly the documented block; omit empty/None optional fields entirely (never send `"allowed_domains": []`). Run the full request shape through LiteLLM's real Anthropic transformation offline; assert the tool block survives verbatim; cite the check. R-024 honesty: transformation proves fidelity — the live smoke run is the acceptance gate.
3. **The family gate:** the gate check runs BEFORE any provider call, in route_call, driven by adapter capability (hasattr/protocol, not a hardcoded family list — a future family adds `search_tool` and the gate opens itself). Fallback chains: if the primary supports search but a fallback family does not, the fallback attempt for a search-enabled request FAILS the gate the same way — a searched request never silently becomes an unsearched one (the never-silently-drop law, applied to capability).
4. **Usage extraction:** discover the real path LiteLLM surfaces the server-tool search count under (R-019/R-022: inspect the real transformation/usage types offline; the live run's debug dump is the final citation). Absent → 0, never a crash. If LiteLLM 1.97.0 does not surface it at all: book it exactly like the ticks finding (P-009 contract 6) — build the safe half, record the gap, the live dump settles it, no speculative parsing.
5. **Meter honesty:** receipts carry `web_search_requests`. Where cost is computed from the map, note in the record when search requests > 0 that token-cost excludes the per-search fee ($10/1k) unless LiteLLM's cost already includes it — discover which, cite it, render honestly (the matrix cost-cell rule: never a figure that looks complete when it is not).
6. **Streaming compatibility:** search-enabled calls must work on BOTH paths — blocking and streaming (the interviewer streams; P-016 depends on this). Offline: fake stream carrying server-tool blocks + terminal usage with a search count → assembled content intact, count extracted, one receipt. Live: prove 5 runs the streaming path.
7. **Smoke prove 5 (`prove_search`):** on the Anthropic family's demo role, streaming, ask a question that REQUIRES current information (e.g. "In one sentence: what is the Bank of England's current base rate? Cite the source."). Print the streamed answer, then the receipt line including `searches=N`. Expected (reported, not asserted): N ≥ 1 and an answer with a citation. Runs only when the anthropic family is present; skipped with a note otherwise. Matrix untouched — search is not a matrix column (per-model search capability is a future question; one demo proves the plumbing).
8. **`max_uses` default is 5 and callers should set it deliberately** — document on the spec that each use is billed; P-016's interviewer wiring will choose a small value (likely 2–3).

## Tests that must pass (ALL offline — fakes at the completion boundary)

test_search.py:
- spec validation: both domain lists set → raises naming both; max_uses bounds enforced
- rendering: minimal spec → exactly the documented block with no empty optionals; full spec → all fields present; R-022 transformation check with citation
- family gate: search-enabled request to a family without search_tool → ProviderCallError naming family, provider never called; anthropic-routed → tools present in the call kwargs
- fallback capability law: primary anthropic + fallback openai on a searched request → fallback attempt gate-fails, error surfaces both models' outcomes
- usage: fake response with the discovered server-tool count path → Usage.web_search_requests set; absent → 0; streamed terminal-usage variant → same
- meter: a record with searches > 0 round-trips through the ledger; the honesty note per contract 5's discovery
- non-search requests: byte-identical behavior to today (no tools kwarg at all — assert absence, the R-018 pattern)

Full suite green — all four packages.

## Forbidden

- No search for any family but Anthropic (the gate enforces; others arrive docs-first).
- No `web_search_20260209` (booked, not built). No web_fetch, no citations rendering, no result parsing beyond what route_call already returns — consumers decide presentation (P-016).
- No registry/role edits. No engine, workspace, or CLI changes.
- No speculative parsing of usage fields never observed (R-019).
- No new dependencies, no keys, no network in tests; only the human runs smoke.
