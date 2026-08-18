# Packet P-005 — Anthropic Polish: Cache Fix (T-002) + Streaming

**Department:** Coding Floor
**Wave:** 4 (builds on P-004, which is stamped)
**Language:** Python 3.12
**Architecture context:** First light (2026-08-18) proved ping, roles, and attachments, and exposed one defect: the cache demo returned creation=0/cached=0 on both calls despite a 2,114-token stable system block — filed as T-002. This packet diagnoses and fixes T-002, and adds streaming as an optional delivery mode. Same gate, same adapter, same meter — streaming changes how the answer arrives, never what is recorded.

## One job

Make prompt caching demonstrably work on real Anthropic calls (creation > 0 on first call, cached > 0 on second), and let a caller receive the answer incrementally via a chunk callback while the meter still records one complete, accurate receipt.

## Ticket T-002 (open with this packet; resolve within it)

Symptom: cache demo zeros on both calls. Two hypotheses, indistinguishable from outside:
- H1 — the `cache_control` mark is not reaching Anthropic (lost in LiteLLM's message transformation, e.g. during system-message hoisting).
- H2 — caching works, but the router reads the wrong field paths off the response usage object.

Also riding along (observation, fix only if root cause is shared): floor_agent (haiku) ignored the system instruction in prove-1 while architect and judge obeyed. Verify the system block is actually present in the request LiteLLM sends for that role; if it is, record "model instruction-following, not a defect" and close.

## Dictionary (existing names unchanged; new names below)

| Concept | Name |
|---|---|
| Chunk callback parameter | `on_chunk` (parameter on `route_call`: `Callable[[str], None] \| None = None`) |
| Debug env flag for smoke | `FOUNDRY_SMOKE_DEBUG` (value "1" enables) |
| Raw-usage dump helper | `dump_usage(response) -> dict` (file: `smoke.py`) — returns the raw usage structure as a plain dict for printing |

## Files to create or modify (each under 300 lines)

```
switchboard/
├── smoke.py                — MODIFY: debug mode + streaming demo (prove 4)
├── src/switchboard/
│   ├── adapters.py         — MODIFY only if T-002 root cause is H1
│   └── router.py           — MODIFY: streaming path; usage extraction fix if H2
└── tests/
    ├── test_router.py      — MODIFY: streaming tests may go here or...
    └── test_streaming.py   — NEW (R-017 precedent): streaming behaviour tests
```

All other files stamped. If diagnosis demands touching another file, R-016 applies: flag the necessary unstamping explicitly in the build log.

## Pinned dependencies

None added.

## Behaviour contract — T-002 diagnosis and fix

1. **Diagnose before fixing.** Add to smoke.py: when env `FOUNDRY_SMOKE_DEBUG=1`, the cache demo additionally prints (a) the exact messages structure handed to completion_fn for call 1 (so the cache_control mark's presence/absence is visible), and (b) `dump_usage()` of both raw responses — every top-level usage field name and value, including nested `prompt_tokens_details` and any `cache_creation_input_tokens` / `cache_read_input_tokens` style fields, whatever their actual names are. No secrets in output.
2. **Fix per root cause.** H1 → correct the adapter's block shape to LiteLLM's documented Anthropic form so the mark survives transformation. H2 → correct the router's usage extraction to the actual field paths observed (checking attribute AND dict access, since LiteLLM usage objects support both inconsistently). Either way: the offline tests are updated so the fake responses mimic the REAL observed shape — fakes that flatter a bug are worse than no fakes.
3. **Acceptance for T-002 is empirical:** the human re-runs `python smoke.py`; call 1 shows creation > 0, call 2 shows cached > 0. The build log records the root cause (H1 or H2) in one sentence.
4. **Floor_agent observation:** with debug on, prove-1 also prints whether a system message is present in floor_agent's outgoing request. Present → close as model behaviour. Absent → that is a second bug; fix it under this packet.

## Behaviour contract — streaming

5. `route_call(..., on_chunk=None)`. When `on_chunk` is None → exactly current behaviour, byte-for-byte. When provided → the call runs with `stream=True`; each text delta is passed to `on_chunk(delta)` as it arrives.
6. **The response is still complete.** After the stream ends, route_call returns the same `SwitchboardResponse` as non-streaming: full `content` (the joined deltas), `model_used`, `usage` (from the stream's final usage data — LiteLLM surfaces provider usage on the terminal chunk; reconstruct via the documented stream-rebuild path), and the meter records exactly one `MeterRecord`, identical in shape to non-streaming. Streaming must never produce a cheaper-looking or missing receipt.
7. **Fallbacks still work.** If the primary raises before or during streaming, the fallback chain proceeds as today. Deltas already delivered from a failed primary are the caller's concern to discard; route_call signals a fresh start by invoking `on_chunk("\n")`? NO — inventing a signal is a design decision the floor must not make. RULING INLINE: on fallback after partial deltas, route_call raises `ProviderCallError` for THAT attempt only internally, proceeds to the fallback, and calls `on_chunk` with subsequent deltas; the returned SwitchboardResponse.content contains ONLY the successful model's full text, so the receipt is always truthful. Callers wanting clean UX should treat a changed model_used as "rerender from response.content". Document this in router.py's docstring.
8. **on_chunk exceptions must not kill the call:** a raising callback is caught, converted to a RuntimeWarning (same pattern as meter failures), and streaming continues without further callbacks — the final response still returns and meters.
9. **Smoke — prove 4 (streaming):** one streaming call to the judge role ("Count from 1 to 10 slowly, one number per line"). Print deltas as they arrive (flush immediately so the human SEES incremental arrival), then print the final receipt line: model_used, tokens, cost. Skipped if any ping failed, as usual.

## Tests that must pass (ALL offline)

test_streaming.py:
- fake streaming completion (a generator of chunk objects mimicking LiteLLM's real chunk shape) → on_chunk receives every delta in order; returned content equals the joined deltas
- usage from the terminal chunk lands in SwitchboardResponse.usage and in exactly one meter record
- on_chunk=None → fake is called WITHOUT stream=True (assert kwarg absent)
- on_chunk raising on the second delta → RuntimeWarning, no further callbacks, full response still returned and metered
- primary fails mid-stream → fallback streams, response.content is the fallback's full text only, model_used is the fallback
- tag gate still first: bad tags → MissingTagsError, fake never called

test_router.py / cache tests: fake response shapes updated to mirror the REAL usage structure observed in diagnosis; cache extraction asserted against that real shape.

Full suite green.

## Forbidden

- No changes to stamped files beyond what T-002's root cause necessarily requires (R-016 flag if so).
- No new dependencies. No async — synchronous streaming iteration only.
- Tests make zero network calls. Only the human runs smoke.py.
- No invented streaming signals or protocol beyond this contract.
