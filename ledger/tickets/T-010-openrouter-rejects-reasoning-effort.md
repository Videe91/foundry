# T-010 — LiteLLM refuses `reasoning_effort` for openrouter, one layer above the transformation

**From:** Live `smoke.py` run 2026-08-19, PROVE 1
**Raised by:** Coding Floor
**Status:** OPEN — needs a ruling; the options trade against the never-silently-drop law
**Severity proposed:** S1 (two shipped roles cannot make a call at all)

## Symptom

PROVE 1 died on `judge_fifth`. Both its models failed:

```
all models failed for role 'judge_fifth': tried openrouter/moonshotai/kimi-k3,
openrouter/deepseek/deepseek-v4-pro-0813; last error:
litellm.UnsupportedParamsError: openrouter does not support parameters:
['reasoning_effort'], for model=deepseek/deepseek-v4-pro-0813.
To drop these, set `litellm.drop_params=True` ...
If you want to use these params dynamically send
allowed_openai_params=['reasoning_effort'] in your request.
```

Ping passed for all three openrouter models — ping sends no effort.

## Diagnosis

```
litellm.get_supported_openai_params(provider="openrouter")
  -> 31 params, reasoning_effort NOT among them   (same for kimi and deepseek)

OpenrouterConfig.transform_request(optional_params={"reasoning_effort":"high"})
  -> {"reasoning_effort": "high", ...}   the transformation carries it fine
```

**`litellm.completion` validates parameters against its supported-params list
BEFORE the transformation ever runs.** The request never reaches the code P-010
verified.

## Why the R-022 check passed and the call still failed

P-010's R-022 check called `OpenrouterConfig.transform_request` **directly** —
the same practice used for every other family — and it was correct about what it
measured: the transformation does carry `reasoning_effort`.

What it skipped is a gate that sits **above** the transformation and only runs on
the real `litellm.completion` path.

**This is R-024 with a new layer.** R-024 established that transformation
fidelity does not prove *provider* acceptance. T-010 adds a third party between
them: **the middleware's own parameter gate.** The stack is

```
our adapter  ->  litellm.completion's supported-params gate  ->  transformation  ->  provider
                 ^^^^ refused here, and nothing we test today looks at this ^^^^
```

The `xai` case is the instructive contrast: P-009 proved LiteLLM passes every
effort level straight through for xai, validating none — so we concluded
load-time validation was the only guard. That conclusion was right for xai and
does not generalise: for openrouter LiteLLM validates **the parameter's
existence**, not its value.

## R-031's blind spot

R-031 ruled that an aggregator declares **no effort vocabulary**, so load-time
validation skips the family — the vocabulary belongs to the routed model. That
reasoning was about **which level** is valid. It did not consider whether the
parameter can be **sent at all**, which turns out to be a family-level fact,
knowable offline, and exactly the kind of thing R-025 exists to catch at load
rather than at call time.

## Affected today

| role | model | effort |
|---|---|---|
| `judge_fifth` | openrouter/moonshotai/kimi-k3 | high |
| `floor_agent_third` | openrouter/deepseek/deepseek-v4-flash-0731 | high |

Both were set to `high` under the standing minimum-effort policy, which is why
this surfaced the moment openrouter roles ran a real prove phase.

## Options — the trade is against the never-silently-drop law

1. **Forward it explicitly.** `litellm.completion` accepts
   `allowed_openai_params=["reasoning_effort"]` via `**kwargs` (confirmed
   present in litellm 1.97.0's `utils.py`; not in the signature, so it is a
   kwargs-only feature). Honours the human's config and sends what was asked
   for. **Unknown:** whether each routed upstream then honours or rejects it —
   that is per-model and only a live run answers it.
2. **Refuse at load.** Extend R-025-style validation: a family LiteLLM will not
   accept `reasoning_effort` for rejects a role that sets one, naming the family
   and the role. Fails at load instead of mid-run — R-025's own principle — but
   contradicts R-031's "skip validation for aggregators" unless that ruling is
   narrowed to *levels*.
3. **Config only.** Remove `effort` from the two openrouter roles (R-012, the
   human's edit). Unblocks immediately and costs nothing, but the standing
   "minimum effort high on every role" policy then cannot apply to openrouter,
   and nothing stops the next person re-adding it.
4. **`litellm.drop_params = True`.** Rejected outright as an option: it silently
   discards parameters across every family, which is the never-silently-drop law
   inverted and would have hidden this defect rather than surfacing it.

**Recommendation: 2 plus 3** — refuse at load so this can never again fail
mid-run, and clear the two roles so the registry loads. Option 1 is worth
knowing about but it buys a live experiment, not a fix: it converts a certain
failure into an unknown one.

## Not fixed pending the ruling

No code changed. Nothing here is a defect in P-010 or P-015 — the openrouter
family works, the roles work without effort, and the ping proved all three
models reachable.
