# T-005 — Gemini: two effort levels rejected, and a forbidden parameter injected

**From:** P-008 discovery (offline, no spend)
**Raised by:** Coding Floor
**Status:** RESOLVED by R-025 — validation moved to registry load; temperature booked as an open R-024 question.
**Severity proposed:** S1 (two of our five effort levels cannot reach this
family; every Gemini call carries a parameter the provider is documented to
have removed)

## Finding 1 — `xhigh` and `max` are rejected outright (contract 3)

Our validated effort set is `low/medium/high/xhigh/max`. Through LiteLLM's real
`GoogleAIStudioGeminiConfig.map_openai_params`:

```
low     -> {"thinkingConfig": {"thinkingLevel": "low",    "includeThoughts": true}, "temperature": 1.0}
medium  -> {"thinkingConfig": {"thinkingLevel": "medium", "includeThoughts": true}, "temperature": 1.0}
high    -> {"thinkingConfig": {"thinkingLevel": "high",   "includeThoughts": true}, "temperature": 1.0}
xhigh   -> RAISED ValueError: Invalid reasoning effort: xhigh
max     -> RAISED ValueError: Invalid reasoning effort: max
```

Not dropped, not mistranslated — **hard-raised**. A role configured
`effort = "xhigh"` or `"max"` and routed to a `gemini/` model raises at call
time, before any request leaves the process. Gemini's docs define three
thinking levels, so the three-level ceiling is the provider's, not LiteLLM's.

The packet forbids inventing a client-side collapse (`xhigh`→`high`) without a
ruling, so no mapping was built and no test pins the raising behaviour — that
would enshrine a defect as expected. The three working levels are pinned.

**Blast radius today:** none. The shipped registry's `architect` and
`architect_max` use `xhigh`/`max`, but both are `anthropic/`. Any future
`gemini/` role must stay at `high` or below until this is ruled.

## Finding 2 — LiteLLM injects `temperature: 1.0` (contract 4)

Contract 4 requires asserting the outgoing payload carries no
temperature/top_p/top_k, "neither from us nor injected by LiteLLM defaults".
That assertion cannot pass. `map_openai_params` returns `{"temperature": 1.0}`
**even with no parameters supplied at all**, and it reaches the request body:

```json
"generationConfig": {
  "thinkingConfig": {"thinkingLevel": "high", "includeThoughts": true},
  "temperature": 1.0
}
```

The packet's architecture context states Gemini 3.6+ removed
temperature/top_p/top_k as accepted parameters. LiteLLM disagrees — its
`get_supported_openai_params` still lists `temperature` and `top_p` for this
model — which is the R-024 situation exactly: **the library's view is not the
provider's acceptance.** Whether Gemini 3.7 rejects the field or ignores it
cannot be settled offline.

Our adapter contributes nothing here; a test pins that half. The injection is
LiteLLM's, and stripping it would mean editing an outgoing payload the router
does not own — not a floor decision.

## Evidence path (reproducible, no network)

Gemini has a custom body builder — `transform_request` on the config raises
`NotImplementedError("Vertex AI has a custom implementation")`. The real path
is `litellm.llms.vertex_ai.gemini.vertex_and_google_ai_studio_gemini.
sync_transform_request_body`, which the new tests use for every R-022 check.
Worth recording: the obvious entry point is a dead end for this family.

## Questions for Cortex

1. **Effort:** ratify a client-side collapse (`xhigh`/`max` → `high` for
   families whose ceiling is lower), or constrain `gemini/` roles to
   `high`-and-below and validate that at registry load, or leave it raising?
   A collapse is the only option that keeps a role portable across families.
2. **Temperature:** accept it (if the provider ignores unknown fields), strip
   it in the router for `gemini/`, or treat contract 4's assertion as
   unsatisfiable and amend it? The live smoke run is the acceptance gate here
   per R-024 — it may resolve itself as a non-issue.
3. **Should the effort ceiling be a registry-load validation** rather than a
   call-time surprise? That generalises: every family has a level set, and
   ours is the union.

---

## RESOLVED — R-025

All three questions ruled; applied in one amendment.

1. **Effort ceilings move to registry load.** Each adapter declares its
   family's levels — Anthropic five, OpenAI five, Gemini three — and
   `load_registry` rejects a role whose effort exceeds its primary model's
   family ceiling. A family without an adapter is not validated: we do not know
   its vocabulary. The error a human now sees:

   ```
   role 'judge_third': effort 'xhigh' exceeds the 'gemini' family ceiling (low, medium, high)
   ```

   Role, family, and ceiling, at load, on a config that was legal to write
   under R-012 — instead of a `ValueError` from inside LiteLLM mid-run.

2. **Not pinning the raising behaviour: ratified.** No test enshrines
   `Invalid reasoning effort` as expected.

3. **Temperature: booked, not fixed.** Our half stays pinned — the adapter
   contributes no sampling parameters. LiteLLM's injected `temperature: 1.0`
   is an open R-024 acceptance question; the live smoke run is the gate. If
   Gemini 3.7 accepts the call it is tolerated-but-noted; if it rejects, that
   is T-006 with the exact error in hand.

**Full suite: 170 passed, 0 failed.** **CLOSED.**
