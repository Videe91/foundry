# Model evidence — per-model live verification

Append-only. What each model in the registry has actually been observed to do,
as opposed to what its family is assumed to do. Family demos prove a family
through one demo role; this ledger records the models themselves.

Everything here is OBSERVED. Where an observation contradicts a vendor's
documentation, both are recorded and the observation wins as a description of
what our code will meet in production.

---

## 2026-08-18 — first per-model sweep, all four families

Run outside `smoke.py` with human authorisation, using the P-009.5 matrix
instrument (`matrix_row`) plus targeted probes. Total spend across every probe
in this session: roughly **$0.35**. All probe meters were written to a scratch
path, so `ledger/meter.jsonl` carries only real smoke runs.

### Coverage before this sweep

Attachments and caching had been live-proven on exactly **one model per family**
— each family's `demo_role_for` pick, which ranks by price. Everything else in
the registry had only ever been pinged and asked PROVE 1's one-line question.
`anthropic/claude-fable-5` had **never made a metered call at all**, being the
sole member of `architect_max`, which is in `EXCLUDED_FROM_PROVE`.

### Results: 8 of 9 models verified

| model | image | pdf | text | cache c1 | cache c2 |
|---|---|---|---|---|---|
| anthropic/claude-opus-5 | — | — | — | — | — |
| anthropic/claude-sonnet-5 | OK | OK | OK | 0/6544 | 6544/0 |
| anthropic/claude-fable-5 | OK | OK | OK | 0/6544 | 6544/0 |
| anthropic/claude-haiku-4-5 | OK | OK | OK | 0/4142 | 4142/0 |
| openai/gpt-5.6-sol | OK | OK | OK | 0/0 | 3674/0 |
| openai/gpt-5.6-terra | OK | OK | OK | 0/0 | 3674/0 |
| openai/gpt-5.6-luna | OK | OK | OK | 0/0 | 3674/0 |
| gemini/gemini-3.7-flash | OK | OK | OK | 0/0 | 0/0 |
| xai/grok-4.6 | OK | REFUSED | OK | 128/0 | 3840/0 |

Cells are `cached/creation`. `REFUSED` is by design (P-009 contract 4).

**Every attachment kind every family claims to support was accepted by every
model of that family.** No adapter shape failed on any model.

### anthropic/claude-opus-5 — unverified, provider capacity

Five attempts over ~25 minutes, every one `overloaded_error`:

```
{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"},
 "request_id":"req_011CeAYj45GAgCcTwBWNbMdg"}
```

Ruled out our side before concluding: it fails identically **streamed and with
`stream=False`**, identically **with and without attachments**, and identically
on a minimal 8-token call. In the same minute, sonnet-5, haiku-4-5 and fable-5
all answered that minimal call. So this is Opus-5 capacity at Anthropic, not a
capability question and not a defect here. Its attachment and cache columns
remain genuinely unknown.

**Consequence worth noting:** `architect` is `opus-5` with fallbacks
`[sonnet-5, gpt-5.6-sol]`. During this outage every architect call ran on
Sonnet-5 instead, correctly and silently. Nothing in the output makes a fallback
substitution visible — you must read `model_used` in the meter to know.

### anthropic/claude-fable-5 — first metered call in the project's history

It was never broken; `prove_roles` skips `architect_max` deliberately, as a
spend guard on the priciest model. Probed directly at its configured
`effort="max"`, with `max_tokens` bounded to 2048 rather than the role's 128000,
because an unbounded max-effort call at $50/MTok output is an open-ended bill:

```
content : 'FOUNDRY ONLINE'
usage   : prompt=30 completion=96
cost    : $0.0051
```

96 completion tokens for a two-word answer — max effort spends thinking tokens
even on trivial prompts. **Not proven:** Fable at `effort="max"` *with*
attachments. The matrix omits effort by design (R-025), so the attachment rows
above ran at no effort.

---

## Cache behaviour differs per family in kind, not just degree

The same instrument, the same byte-identical prefix, four families:

| family | prefix | call 1 | call 2 | mechanism |
|---|---|---|---|---|
| anthropic | 6544 | 0/6544 | 6544/0 | explicit mark; creation counter; warms in seconds |
| openai | 3674 | 0/0 | 3674/0 | provider-side; **no creation counter**; warms in seconds |
| xai | 3936 | 128/0 | 3840/0 | provider-side; 128-token blocks; **asynchronous** |
| gemini | 3669 | 0/0 | 0/0 | never engaged at this size — see below |

`creation=0` on openai, gemini and xai is correct rather than missing: only
Anthropic takes an explicit mark, so only Anthropic reports a creation counter.
This is what `test_cache.py` pins and what the corrected `cache_expectation_for`
line now prints — previously the demo printed Anthropic's expectation at every
family, making a textbook provider-side hit read as a failure.

---

## Gemini: caching works. The documented minimum is necessary but NOT sufficient

`gemini-3.7-flash` had **0 cache hits in 12 byte-identical calls** at a 3669-token
prefix, spanning 13:05 to 16:51. That was logged in R-027 as
observed-not-explained. It is now explained, and the explanation cost one wrong
hypothesis first.

**Google's documentation** lists `gemini-3.7-flash` at a **4,096-token minimum**
for implicit caching, which is enabled by default for 2.5 and newer. Our block
is 3,721 tokens as Gemini counts it — 375 short. That looked like the whole
answer, and it was wrong.

**Measured, 9 byte-identical pairs, one session, only the size varying:**

| prompt tokens | cached on call 2 | |
|---|---|---|
| 3,669 | 0 | our current block; 12 prior observations agree |
| 4,584 | 0 | **clears the documented 4,096 and still caches nothing** |
| 4,889 | 0 | |
| 5,316 | 0 | |
| 5,682 | 0 | |
| 6,109 | 4,071 | engages here |
| 7,939 | 4,076 | |
| 9,769 | 4,080 | |
| 12,209 | 8,167 | |

1. **The effective engagement boundary is between 5,682 and 6,109 tokens** —
   about 1.5x the documented minimum.
2. **Caching quantises into ~4,096-token blocks.** Cached amounts sit at 4,071 /
   4,076 / 4,080 then jump to 8,167 — consistently ~25 under one and two blocks.
   Gemini commits whole blocks only, which is why 4,584 tokens (one block plus
   change) gets nothing.
3. **Position is irrelevant.** The same tokens sent as `systemInstruction` and
   inside a user message behave identically: neither caches at 4,651, both cache
   at 12,401. Our adapter is not putting the block in the wrong place.

**Why this matters beyond Gemini:** sizing the block to just clear 4,096 would
have shipped a fix that does not work, and **every offline test would still have
passed**, because no test asserts a live cache hit. That is T-002's trap a
second time — the shared `CACHE_SYSTEM_BLOCK` was sized for Anthropic's 2,048
minimum, clears OpenAI's 1,024 comfortably, and sits below Gemini's real bar. One
constant, four families, one silent failure: the R-014 corollary exactly.

**Not fixed here.** Raising the block is a shared-fixture change that raises
every family's demo cost, and the burden lands on the most expensive model:

| block size | Gemini caches | fable-5 cache demo (2 calls) |
|---|---|---|
| 3,721 (current) | no | ~$0.074 |
| ~6,200 | yes, 1 block | ~$0.124 |
| ~12,400 | yes, 2 blocks | ~$0.248 |

Booked as **T-007** for a ruling.

---

## xAI: the "128-token floor" is not a floor, it is the block size

R-027 logged *"a ~128-token floor is cached even on a 219-token prompt"* and
*"cross-run persistent, not immediately available"*. Both readings need
correcting.

**Measured across five prefix sizes:**

| paragraphs | prompt | call 1 cached | call 2 cached | |
|---|---|---|---|---|
| 20 | 1,456 | 128 | 1,408 | caches at a tiny prefix |
| 40 | 2,696 | 128 | 2,688 | |
| 60 | 3,936 | 128 | 128 | did not warm within the run |
| 100 | 6,416 | 2,560 | 128 | **went backwards** |
| 160 | 10,136 | 6,400 | 10,112 | |

**Every observed value is an exact multiple of 128** — 7 for 7, including the
3,840 from an earlier run:

```
  128 = 128 x 1     2,560 = 128 x 20     6,400 = 128 x 50
1,408 = 128 x 11    2,688 = 128 x 21    10,112 = 128 x 79
3,840 = 128 x 30
```

So **128 is xAI's cache quantum, not a fixed system-side segment.** The
"constant 128 floor" was one committed block. This is a cleaner explanation
than the one R-027 records, and it also explains the 12-minute delay: cache
commitment is **asynchronous and eventually consistent**, so a byte-identical
pair seconds apart can see 128, then 128 again, then 2,560, then drop back to
128. The 6,416-token row going *backwards* between calls is the clearest
evidence — a synchronous cache cannot do that.

**Practical consequence:** xAI cache figures are not reproducible within a run
and must never be asserted. The existing note is right to report and not
explain; it should now say "128-token blocks, committed asynchronously" rather
than "a ~128-token floor".

---

## Two cross-cutting findings

### `max_tokens` must cover reasoning plus visible output

First seen on Gemini, then confirmed on Anthropic. At `max_tokens=32`,
`gemini-3.7-flash` returned **29 completion tokens and zero visible text**, all
of them `reasoning_tokens`, with `finish_reason="length"`. At 512 the same
prompt answered normally. In a separate control run at `max_tokens=8`,
`sonnet-5` and `fable-5` both returned empty content on blocking calls for the
same reason.

A cap that only fits the answer yields a **successful, correctly-metered call
with nothing in it** — a confusing thing to debug cold. No role in the registry
is near this cliff (lowest ceiling is 8,000), but a future ceiling reduction
would meet it.

### The matrix cannot distinguish "failed" from "unavailable"

Opus-5's outage rendered as five `FAIL(...)` cells, identical in form to a real
capability failure. A reader skimming that grid would conclude Opus-5 cannot
handle attachments, which is not what happened.

This follows directly from a P-009.5 decision: the pinned registry carries **no
fallbacks**, so nothing papered over the outage. The instrument behaved as
specified — the *rendering* is ambiguous. Candidate fixes, both packet
decisions: a distinct `UNAVAILABLE` cell for 5xx/overload conditions, and/or a
bounded retry before recording a failure.

---

## Ledger corrections requested

1. **R-027's xAI observation** should read "128-token blocks, committed
   asynchronously" rather than "a ~128-token floor". Evidence: 7 of 7 values
   exact multiples of 128, and one pair that went backwards.
2. **R-027's Gemini observation** — "mechanism threshold/timing unknown" — is
   now measured: effective engagement between 5,682 and 6,109 tokens, quantised
   in ~4,096-token blocks, position-independent.
3. **T-007** to be filed for the undersized `CACHE_SYSTEM_BLOCK`, with the cost
   tradeoff above as the decision to rule on.

---

## 2026-08-19 — Interviewer bake-off: the founder's verdict

First live use of P-014's blind trial. Three candidates, shuffled, labelled
A/B/C, mapping revealed only after the read. The founder answered all three in
their own words — no simulation, per the packet.

**Verdict: `anthropic/claude-sonnet-5` confirmed as `interviewer`.** The
existing registry placeholder **stands** — the bake-off's job was to test that
placeholder, not to assume it, and it survived contact.

**Runner-up: `openai/gpt-5.6-terra`**, noted for future **per-project**
registries. This is exactly the mechanism design doc 16.2 rule 2 describes: a
project whose founder reads better with a different voice overrides the global
brains with its own `registry.toml`, and nothing else changes.

| candidate | model | outcome |
|---|---|---|
| A | anthropic/claude-sonnet-5 | **confirmed** |
| B | openai/gpt-5.6-luna | — |
| C | openai/gpt-5.6-terra | runner-up, per-project candidate |

No registry edit was made by the tool. R-012 held: the bake-off produced
evidence and the human made the decision — which in this case was to keep what
was already there.

### T-009's fix held in the field

**All three candidates opened clean.** Not one mentioned the reserved research
slot, on the first live interviews run after the fix. That is the acceptance
gate the offline string guard could not provide: the guard proves nothing in our
code puts the word in front of a model, and only a live run can show that no
model volunteers it anyway.

Recorded as held, not as proven-forever — three candidates on one project is
evidence, not a law. Full transcripts live in the project's own
`ledger/evidence.md`, which stays out of the factory repo under the git law
(Section 16.3): the project's audit trail travels with the project.
