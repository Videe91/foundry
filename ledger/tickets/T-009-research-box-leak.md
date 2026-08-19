# T-009 — The research box leaked into the conversation

**From:** Live interview, 2026-08-19
**Raised by:** Cortex
**Status:** RESOLVED — fixed 2026-08-19.
**Severity proposed:** S2 (no data is wrong; the founder is asked to account for
our plumbing, which is a credibility defect rather than a correctness one)

## Symptom

The interview raised `research` — a box the founder never mentioned and which is
not theirs to answer. It is the reserved slot: filled by the research
department, seeded settled at birth, and by design never conversational.

## Diagnosis — confirmed against the rendered prompt, not assumed

Cortex's suspected root was right in shape and had **two doors**, not one.

### Door 1 — the Interviewer's status map

`box_status()` returned every box, so the state block put this in front of the
Interviewer on **every single turn**:

```json
"box_status": {
  "goal": "empty", "users": "empty", "workflows": "empty", "data": "empty",
  "boundaries": "empty", "research": "confirmed",
  "non_negotiables": "empty", "website": "empty"
}
```

Note what the same dump shows about `incomplete_boxes`: it excluded `research`
**by accident**, not by rule — research is complete, so it fell out of the list.
An internal box that was ever *incomplete* would have leaked into the directives
as something to go and ask about.

### Door 2 — the Scribe's key list

`SCRIBE_SYSTEM` spelled the keys out inline:

```
The eight box keys are: goal, users, workflows, data, boundaries, research,
non_negotiables, website.
```

So the Scribe was told `research` was a box it could fill. Its turn-one
restatement put the word in the transcript, and the transcript is what the
Interviewer reads — which is how a founder ended up being asked about it.

## Fix

**The concept was missing, not the filter.** `internal: bool` is now a property
of a Box in `skeleton.py`, declared once as data, with `CONVERSATIONAL_KEYS`
**derived** from it rather than listed again — a second hand-written list is a
second thing to forget.

Everything model-facing filters through it:

- `box_status()` — conversational only (**the leak**)
- `build_directives()` — `incomplete_boxes` and `pending_confirmations` filtered
  by rule now, not by luck
- the `current_boxes` map the engine hands the Scribe
- the Scribe's key list, derived from `CONVERSATIONAL_KEYS`

Engine changes are **R-016 flagged**: `engine.py` and `state.py` belong to
P-013.

## R-030 sweep — two more instances, both in human-facing output

Not model leaks, but both misreported:

1. **`0 of 7`, not `1 of 8`.** `/status` and the resume recap counted the
   reserved slot, so a founder who had said nothing was told "1 of 8 boxes
   complete". The progress bar was flattering itself at their expense.
2. **The reserved box claimed an author.** It was seeded `proposed_by="user"`,
   so the table told the founder they had confirmed something nobody ever asked
   them about. Now `None`.

The human is still *shown* the slot — they are entitled to see their own
project's state. The fix is that it is labelled as ours and not counted as
theirs: `(plus 1 reserved internally: research — not yours to answer)`.

No play-back rendering exists yet (P-015). `CONVERSATIONAL_KEYS` is the thing it
should render from when it arrives.

## Guard, and its honest reach

`test_internal_boxes.py` checks the **rendered prompt string** — what a model
actually sees — for every internal key, on the system block and messages of both
brains, end to end through `run_turn`.

**What it cannot do**, stated in its own docstring rather than left for a reader
to discover: it cannot prove a model will never *say* "research" (it might, from
its own priors, or because a founder does), and it cannot see a prompt some
future composer builds elsewhere. It proves nothing in this code puts the word
in front of a model, which is what T-009 was.

**Demonstrated discriminating**, each door reverted independently:

```
door 1 reverted (box_status returns all boxes):
  E  assert 'research' not in '...'
     'research' is contained here:
       "boundaries": "empty", "research": "confirmed", "non_negotiables": ...

door 2 reverted (scribe prompt names the eight keys inline):
  2 failed, 10 passed

both restored:
  12 passed
```

A companion test asserts the Scribe is still told about **every** conversational
box — a prompt naming no boxes at all would pass the leak test and leave the
Scribe unable to work.

## Tests

**580 passed** — Switchboard 350 + Workspace 92 + Intent 53 + CLI 85. Two older
CLI tests were updated: they asserted `1 of 8` and `2 of 8`, pinning the padded
count this ticket removes.
