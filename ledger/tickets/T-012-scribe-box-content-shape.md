# T-012 — The Scribe returned a box shape the completeness rules cannot read

**From:** Found while diagnosing T-011, `uk-lead-verify`, 2026-08-19
**Raised by:** Coding Floor
**Status:** RESOLVED — fixed 2026-08-19.
**Severity proposed:** S1 (**no live interview could ever complete** — every box
was stored in a shape its rule cannot evaluate)

## Symptom

Box content in the live state file:

```json
"goal": {"content": "Build a genuine lead verification solution for the UK
                     market (similar to TrustedForm/Journaya...)",
         "status": "proposed", "proposed_by": "user"}
```

What `goal_rule` reads: `content["summary"]` and `content["victory_conditions"]`.
Neither exists here, so the box can never be complete — and nothing said why.

## Diagnosis — the prompt, and worse, the context

The packet asked which layer was at fault. **Both, and they reinforced each
other.**

**1. The prompt taught nothing.** It said, literally:

```
"boxes": {box_key: {content object}}   content you can now fill or update
```

"content object" is not a schema. The per-box shapes in `rules.py` were never
stated anywhere the model could see them, so it had to invent one.

**2. The context demonstrated the WRONG one.** `run_turn` passes
`current_boxes` as `{key: BoxState.model_dump()}`:

```json
{"goal": {"key": "goal", "content": {}, "status": "empty", "proposed_by": null}}
```

Shown that and told nothing, the model mirrored it — returning exactly
`{"content": ..., "status": ..., "proposed_by": ...}`, BoxState minus `key`.

**We taught it the wrong shape by example while failing to teach the right
one.** The model behaved reasonably; the instruction was the defect.

## Why 701 green tests missed it

**Every offline scribe fake returned the correct shape.** They were written from
the schema in the author's head, not from anything a model had produced. R-019
says fakes model the API — here the "API" is *what a real model actually
returns*, and no fixture had ever met one.

This is the flattering fixture in its purest form: the fake could not fail the
way reality did, because the fake was built by the same understanding that was
wrong.

## Fix — both layers

**The prompt now states each box's schema**, taken from what `rules.py`
requires, with the trap named explicitly:

> Do NOT wrap content in `{"content": ..., "status": ..., "proposed_by": ...}` —
> that is the shape you are SHOWN in "Current boxes", and it is not the shape
> you return.

It also prefers absence to partial: *"If you do not yet have enough for a box's
full schema, leave the box out entirely. A partial object is worse than an
absent one: it looks answered."*

**The parser unwraps or rejects, never silently accepts** (`shapes.py`):

- a wrapper whose inner `content` is an **object** → **unwrapped**; the
  extraction is there and only the envelope is wrong, so discarding it would
  throw away work the model did
- a wrapper around a **string** — the observed case → **rejected**
- content that is not an object at all → **rejected**

Rejection triggers **one corrective retry** whose instruction **names the actual
problem**. A generic "that was not JSON" cannot fix a reply that *was* valid
JSON in the wrong shape.

**The prompt and the rules are now tied together by a test.** Each schema the
prompt teaches is run through the real rule function; if a rule changes, the
test fails until the prompt is updated. They can no longer drift silently.

## Fixtures corrected (R-019)

`tests/test_scribe_shape.py` uses the **observed** shape, copied verbatim from
`projects/uk-lead-verify/intent/interview-state.json`, before the corrected one:
the wrapped reply is rejected, the retry names the box and the wrapper, and two
wrapped replies fail loudly with the raw reply preserved in the project build
log. A companion asserts the observed content **fails `goal_rule`** — which is
the reason rejection is right rather than pedantic.

## The state file: RESET, not repaired

`goal`, `users` and `workflows` were reset to `empty`; the transcript and
`turn_count` are untouched.

**Repair was rejected on principle.** Reshaping that content into the schema
would mean *inventing* the `victory_conditions` the founder never gave —
Foundry writing part of a constitution and presenting it as theirs, which is
exactly what R-033b forbids. The wrapped string is a summary of their message,
not their answers.

Reset costs nothing real: **the founder's own words are preserved in the
transcript**, and the Scribe re-extracts from it on the next turn under the
corrected prompt. A backup of the pre-fix file sits beside it as
`interview-state.pre-T-012.json`. Both live under `projects/`, so neither
reaches the factory repo (the git law).

## Tests

**721 passed** — Switchboard 427 + Workspace 92 + Intent 81 + CLI 121.
`shapes.py` is a new module (R-017): `brains.py` reached 305, and "is this shape
readable" is a different job from "wire a model to a callable".
