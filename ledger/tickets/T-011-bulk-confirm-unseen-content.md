# T-011 — The Interviewer asked the founder to confirm three boxes they had never seen

**From:** First real interview, `uk-lead-verify`, turn one, 2026-08-19
**Raised by:** Cortex
**Status:** RESOLVED — fixed 2026-08-19.
**Severity proposed:** S1 (a founder could have signed a constitution containing
words they never read; consent is the one thing Intent exists to protect)

## Evidence — the transcript, verbatim

```
--- user ---
I have seen US has things like trustedform/Journaya that helps clients identified
that the lead sent to them is genuine but UK lacks that and i want a genuine way
we can build it for the UK market and later we can turn this whole into an ai
powered lead management software like Databowl, Leadbyte

--- interviewer ---
Got it — so the goal, the users, and the workflows you've laid out so far all
sound right to me, but before we dig into new territory: can you confirm those
three pieces are settled as you described them, so we don't revisit them later?
```

State after that turn: **three boxes `proposed`, none ever shown.**

```
goal        status=proposed   proposed_by=user
users       status=proposed   proposed_by=user
workflows   status=proposed   proposed_by=user
```

## Diagnosis — against the real directives, not the description

Reconstructed the exact payload the Interviewer received for that turn:

```json
{
  "incomplete_boxes": ["goal","users","workflows","data","boundaries",
                       "non_negotiables","website"],
  "pending_confirmations": ["goal", "users", "workflows"],
  "unsurfaced_contradiction": null,
  "ask_one_question": true
}
```

```
does it receive the proposed CONTENT anywhere?
  goal content in the prompt payload: False
  any box content at all           : False
```

**Three defects, and the third is the root.**

1. **`pending_confirmations` was an uncapped LIST.** Three box names handed over
   at once. Contrast `unsurfaced_contradiction`, deliberately capped at one
   since P-013. The asymmetry was the bug: confirmations simply never got the
   equivalent rule.

2. **The prompt invited exactly this.** The line read: *"If confirmations are
   pending, ask for them directly — 'shall I take that as settled?' — because
   nothing counts until they say so."* Plural, no mention of showing anything,
   and a suggested phrasing that contains no content.

3. **The Interviewer was never given the box CONTENT — only names.** This is
   the root. The model *could not* show what had been understood, because it had
   never been told. "As you described them" was the model papering over an
   information gap we created. Given only the word `goal`, there was nothing
   more specific it could honestly say.

**So this was not a wording problem with a wording fix.** No prompt could make
the Interviewer show content it does not have.

## Fix

**Engine (R-016 flagged — `engine.py` is P-013's):**

`build_directives` now emits `pending_confirmation` — **singular**, carrying
`{box, content, proposed_by}` for at most one box, in skeleton order. It mirrors
`unsurfaced_contradiction` exactly, which is the rule that already worked.

`TurnResult.pending_confirmations` keeps the full list. **The cap is on what
reaches the model, not on what the CLI knows** — capping both would hide pending
work from the human, and a test pins that distinction.

**Prompt:**

> If a pending_confirmation is given to you, it carries the box's CONTENT. Show
> that content back in plain words and ask about THAT ONE THING only — never
> several at once, and never a box whose content you were not given.
>
> Say what you understood, in your words, and ask whether it is right: "here's
> what I understood — did I get that right?" Never say "as you described" or "as
> you said" about content the founder has not seen on screen. What you are
> holding is OUR reading of their message, not their words back to them, and
> asking them to bless an unseen summary of their own idea is how a constitution
> gets signed by accident.

The banned phrase is **named in the prompt** so it can be banned, and named in a
test so the ban survives editing.

## The same turn, after the fix

```json
"pending_confirmation": {
  "box": "goal",
  "content": {"content": "Build a genuine lead verification solution for the UK
               market (similar to TrustedForm/Journaya available in the US).
               Phase 2: expand into an AI-powered lead management platform..."},
  "proposed_by": "user"
}
```

One box. With its words. The Interviewer can now ask an honest question.

## On provenance

All three boxes carried `proposed_by="user"` because `ScribeUpdate.proposed_by`
defaults to `BY_USER` when the Scribe does not say. That default is defensible —
the substance did come from their message — but it cannot distinguish *"the
founder said this"* from *"our rendering of what the founder said"*.

The fix therefore does not lean on `proposed_by` for the wording. **Even
user-derived content is our reading**, so the prompt speaks in "here's what I
understood" terms regardless of who is recorded as proposing it. `proposed_by`
is still passed through, so an interviewer-authored default can be flagged more
strongly, and a test pins that it arrives.

## Observed while diagnosing — NOT this ticket, not fixed

The live Scribe returned box content shaped like a `BoxState`
(`{"content": ..., "status": ..., "proposed_by": ...}`) rather than the schema
`goal_rule` expects (`summary` + `victory_conditions`). That content can never
satisfy completeness. It is a separate defect in the Scribe's output contract,
recorded here because it was visible in the same state file, and left alone
because fixing it is not what this ticket authorised.
