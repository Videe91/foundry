# T-013 — A turn hung, and nothing on screen could tell you it had

**From:** Live interview, `uk-lead-verify`, turn 9, 2026-08-19
**Raised by:** Founder ("why did it hang")
**Status:** RESOLVED — fixed 2026-08-19.
**Severity proposed:** S2 (nothing was lost; the founder had no way to know that)

## Symptom

Mid-interview, a turn produced no output. `/status` typed afterwards did
nothing. The session appeared dead.

## Diagnosis

**The turn never completed.** `run_turn` persists only at the end, and the state
file's transcript stops at the previous exchange — the founder's message is not
there. So the call was still in flight, and the `/status` text sat unread in the
terminal buffer.

**Two defects, and together they made "slow" and "dead" indistinguishable.**

**1. The interview loop showed no sign of working.** Between enter and the first
delta, `session.py` printed nothing at all. `research_cmd` had a working line;
the interview loop had none. And a searched turn is silent *by nature* — the
model searches server-side before emitting any text, so there are no deltas to
show during it. Search was demonstrably active that session: the billing answer
cited real LeadByte and Databowl specifics.

**2. There was effectively no timeout.** We passed none, and
`litellm.request_timeout` defaults to **6000 seconds — 100 minutes**. A stalled
connection would hang for over an hour before erroring.

**Which one actually happened cannot be determined from here, and that is the
defect.** The interface could not distinguish a model thinking hard from a
connection that died. Neither could the founder.

## Fix

**Progress line** (`session.py`). `[thinking…]` before every brain call,
`[thinking — may be searching…]` for a search-enabled role, cleared the moment
the first delta arrives or a blocking call returns. **Silence now always means
working.** The clear is ordered before the reply prints, because a reply
rendered under a stale marker reads as garbage.

**Timeouts as role-class knowledge** (`timeouts.py`):

| role | deadline | retries |
|---|---|---|
| interviewer | 120s | 1 |
| scribe | 60s | 1 |
| researcher | 300s | **0** |

The retry is safe **only because a turn is idempotent**: `run_turn` persists
nothing until the whole turn completes, so a stalled attempt leaves no trace and
a second starts from identical state.

**The researcher deliberately does not retry.** It searches up to eight times; a
silent second attempt would double a deliberately expensive operation without
anyone choosing to spend it. It surfaces immediately.

Applied by passing a timeout-bound `completion_fn` into `route_call` — so **the
Switchboard needed no change** to learn about deadlines.

The error names the role, the elapsed wait, and what the founder actually needs
to know:

```
the 'interviewer' took longer than 121s and was given up on. Nothing is lost —
the interview is saved after every completed turn. Resume with:
python -m foundry_cli intent uk-lead-verify
```

## R-030 sweep

**These three are the only live-call sites in the CLI today**, and all three
have a declared class — asserted by a test. A future role inherits the
interviewer's class rather than silently getting litellm's 100 minutes.

## Guards worth naming

- **A non-timeout error is never retried.** Retrying a real failure would hide
  it behind a duplicate; a test pins that `ValueError` and `RuntimeError` pass
  straight through.
- **Timeouts are recognised by name across libraries** — litellm, httpx and
  asyncio each raise their own type. Matching on the name is a heuristic over
  other people's types, and the code says so rather than pretending otherwise.
- **Structure, not exact seconds.** The test asserts the *ordering* — scribe <
  interviewer < researcher — and that every class sits far below litellm's
  default. The specific numbers are a spend-and-patience tradeoff and may be
  tuned without a red suite.
- **Clearing twice is harmless**, since the first delta clears the line and the
  call's return would clear it again.

## Also confirmed in the same state file

**T-011 and T-012's fixes held in the field.** Three boxes confirmed with the
**correct** schemas — `goal` carrying `summary` and `victory_conditions`,
`users` carrying `users`, `data` carrying `entities` and `sensitive` — and the
transcript shows the Interviewer showing content back one thing at a time:
*"Here's what I understood — … did I get that right?"*

Eight turns saved. The founder lost exactly one message.
