# T-007 — CACHE_SYSTEM_BLOCK sits below Gemini's effective cache threshold

**From:** Per-model sweep 2026-08-18 (see `ledger/model-evidence.md`)
**Raised by:** Coding Floor
**Status:** RESOLVED — ruled as R-028 (2026-08-18).
**Severity proposed:** S2 (the demo reports truthfully, but reports a
non-event; no production path is wrong)

## Symptom

`gemini/gemini-3.7-flash` produced **0 cache hits in 12 byte-identical calls**
at our shared 3,721-token prefix, spanning 13:05–16:51 on 2026-08-18. The other
three families all cache with the same block.

## Diagnosis

`CACHE_SYSTEM_BLOCK` is `_CACHE_PARAGRAPH * 60` = **3,721 tokens**. It was sized
in P-005 to clear **Anthropic's 2,048** minimum (that was T-002). It also clears
OpenAI's 1,024 comfortably. It does **not** clear Gemini's bar.

One shared constant, four families, one silent failure — the R-014 corollary
exactly: *config-independence must hold in every dimension, not just the
asserted one.*

## The documented number is necessary but not sufficient

Google documents `gemini-3.7-flash` at a **4,096-token minimum** for implicit
caching. **Sizing to clear 4,096 would not have worked.** Measured, 9
byte-identical pairs in one session, only the prefix size varying:

| prompt tokens | cached on call 2 |
|---|---|
| 3,669 | 0 |
| 4,584 | 0 ← clears the documented 4,096, caches nothing |
| 4,889 | 0 |
| 5,316 | 0 |
| 5,682 | 0 |
| 6,109 | 4,071 |
| 7,939 | 4,076 |
| 9,769 | 4,080 |
| 12,209 | 8,167 |

- Effective engagement boundary: **between 5,682 and 6,109 tokens**.
- Caching **quantises into ~4,096-token blocks** (4,071 / 4,076 / 4,080, then
  8,167 — each ~25 under a multiple). Whole blocks only, which is why one block
  plus change gets nothing.
- **Position is irrelevant**: identical results for `systemInstruction` vs a
  user message at both 4,651 (neither caches) and 12,401 (both do). The adapter
  is not misplacing the block.

## Why no test caught it, and would not have

No test asserts a live cache hit — cache values are OBSERVED, never asserted
(R-014), which is correct. So a fix sized to the documented 4,096 would have
gone green offline and still cached nothing live. **This is T-002's trap a
second time**, and the second time it was the vendor's own documented number
that would have misled us.

## Proposed fix — needs a ruling, because it costs money

Raise `CACHE_SYSTEM_BLOCK` past the measured boundary. The block is shared by
all four families' cache demos, so the cost lands hardest on the priciest model:

| block size | Gemini caches | fable-5 cache demo (2 calls, $10/MTok in) |
|---|---|---|
| 3,721 (current) | no | ~$0.074 |
| **~6,200** | yes, 1 block | ~$0.124 |
| ~12,400 | yes, 2 blocks | ~$0.248 |

Recommendation: **~6,200 tokens** (`_CACHE_PARAGRAPH * 100`), which clears the
measured boundary with margin and caches one block. Two blocks buys a larger
observed number for roughly double the spend and demonstrates nothing extra.

Alternative worth ruling on: a **per-family block size**, so Anthropic and
OpenAI demos stay cheap while Gemini gets the prefix it needs. That costs a
shared-fixture split and breaks the "byte-identical across families" simplicity
the current demo relies on.

## Guard to add with the fix

The missing instrument, and the direct analogue of R-027's known-content-minimums
list applied to the cache fixture rather than the image: a **per-family cache
minimum table** asserted against the block, recording that Gemini's *effective*
threshold is ~6,100 and **not** the documented 4,096. Whatever the ruling, the
measured number and the documented number should both be written down, since
they disagree.

---

## Resolution — R-028

Ruled: the shared constant is **retired**, and cache demo blocks are **per
family**, each sized to its own measured minimum plus margin and declared beside
that family's cache note. Neither proposed single size was adopted; the
per-family option was, so Anthropic, OpenAI and xAI demos stay at ~3,721 tokens
and only Gemini pays for the larger prefix (105 paragraphs, ~6,511 tokens).

An undeclared family falls back to the **largest** declared block, never the
smallest — undersized is the failure mode this ticket was.

`CACHE_SYSTEM_BLOCK` no longer exists, and a test asserts its absence by name:
a module-level constant was what made the undersizing invisible, since no call
site named a family.

**The guard demanded by this ticket is in place and is discriminating.** One test
asserts every family's block clears that family's measured minimum; a second
asserts the *retired* 60-paragraph size still clears anthropic, openai and xai
while falling below gemini's minimum — so the guard cannot pass under the old
rule. The measured minimum (6,109) and the documented one (4,096) are both
written down, since they disagree.

Also removed: a dead duplicate of `_CACHE_PARAGRAPH` and `CACHE_SYSTEM_BLOCK`
that had sat unused in `smoke.py` since the P-005 split.
