# T-002 — Prompt cache returns zeros on both calls

**From:** First light 2026-08-18, opened by P-005
**Raised by:** Coding Floor
**Status:** CLOSED — confirmed fixed on the live run of 2026-08-18.
**Severity proposed:** S1 (a headline feature silently does nothing)

## Symptom

The cache demo called `floor_agent` twice with an identical system block.
Both receipts: `cached_tokens=0`, `cache_creation_tokens=0`, `prompt=2114`.
No error, no warning — the provider simply did not cache.

## Hypotheses under test

- **H1** — the `cache_control` mark never reaches Anthropic (lost in LiteLLM's
  message transformation, e.g. during system-message hoisting).
- **H2** — caching works, but the router reads the wrong field paths off the
  response usage object.

## Diagnosis — both hypotheses REFUTED, offline, zero spend

**H1 is refuted.** Our adapter's payload was run through LiteLLM's real
`AnthropicConfig.transform_request`. The mark survives and arrives in the
top-level `system` parameter:

```json
"system": [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]
```

`translate_system_message` explicitly copies `cache_control` from list-form
system content blocks. Our block shape is exactly the form it handles.

**H2 is refuted.** A real `litellm.types.utils.Usage` object was built the way
LiteLLM builds one for Anthropic and passed to our `_extract_usage`:

```
anthropic creation=2114 read=   0  ->  ours cached=   0 creation=2114
anthropic creation=   0 read=2114  ->  ours cached=2114 creation=   0
```

Both field paths are correct: `prompt_tokens_details.cached_tokens` for reads,
top-level `cache_creation_input_tokens` for writes.

## Root cause — the cache prefix was below Anthropic's minimum

Measured with `litellm.token_counter`:

```
cache system block: 1560 words -> ~1861 tokens
Anthropic minimum cacheable prefix: 1024 (Opus/Sonnet), 2048 (HAIKU)
margin over haiku minimum: -187 tokens
```

`floor_agent` is haiku-4-5, whose minimum is **2048**. The marked prefix was
**1861 tokens — 187 short**. Anthropic silently declines to cache a prefix
below the minimum; it does not error.

The observed `prompt=2114` misleads: that is the *total* prompt (system + user
+ framing). Only the cache-marked prefix counts toward the minimum, and that
was 1861. P-004's smoke comment — "long enough to clear Anthropic's minimum
cacheable size" — was true for Sonnet/Opus at 1024 and false for Haiku at 2048.

## Fix built in P-005

The cache block is enlarged well past 2048 so it clears the Haiku minimum with
margin, and the demo prints its own measured token count beside the applicable
minimum so a future shortfall is visible rather than silent. Debug mode
(`FOUNDRY_SMOKE_DEBUG=1`) dumps the outgoing message structure and the raw
usage fields of both responses.

**Acceptance is empirical:** the human re-runs `python smoke.py`; call 1 must
show creation > 0 and call 2 cached > 0. Until that run this ticket stays
DIAGNOSED, not CLOSED.

## Rider — floor_agent ignored the system instruction

The system block **is** present in floor_agent's outgoing request: the same
`transform_request` check shows it hoisted into the `system` parameter for that
role exactly as for architect and judge. Not a missing-system bug. Recorded as
**model instruction-following** — haiku-4-5 is simply less literal about
"Reply with exactly" than opus-5 and sonnet-5. Debug mode prints system-block
presence per role so this stays checkable. Closed as not-a-defect.

---

## CLOSED — live run 2026-08-18

The human re-ran `python smoke.py`. Prompt caching works:

```
call 1: cache_creation_tokens = 4142   (cache written)
call 2: cached_tokens         = 4142   (cache read)
```

Both acceptance conditions met — creation > 0 on the first call, cached > 0 on
the second. **Root cause confirmed as diagnosed:** the prefix was below
Anthropic's minimum cacheable size for the model, and nothing was wrong with
the `cache_control` mark (H1) or the router's usage field paths (H2). Enlarging
the prefix past haiku-4-5's 2,048-token minimum was the whole fix.

The measured 4,142 tokens on the live run against the offline estimate of 3,721
is expected: `litellm.token_counter` approximates, Anthropic's tokenizer is
authoritative. Both are comfortably clear of 2,048, which is the point.

**Rider closed:** the floor_agent system-instruction observation is confirmed as
**model behaviour, not a defect** — the system block is present in the outgoing
request, verified both offline against LiteLLM's transformation and live via
debug mode. haiku-4-5 is simply less literal than opus-5 and sonnet-5 about
"Reply with exactly".

**T-002 is closed.**
