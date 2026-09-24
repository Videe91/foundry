# Model Runtime — MR6: GPT-6 Astra through the frozen Intent certification exam

Base: `e1d0242eacd3274fb0c913566e24473e7cbe3536` (MR5 accepted).

MR6 answers one question: **can `openai/gpt-6-astra` earn the same `INTENT_SYNTHESIS`
certification `xai/grok-4.7` earned, against the same frozen Intent Engine, the same five
semantic cases, and the same deterministic scoring?** The only legitimate variable is the
contestant.

It runs in two checkpoints. **Checkpoint 1 (this document) makes the harness
contestant-neutral and takes no live OpenAI calls.** Checkpoint 2 runs the exam.

## Checkpoint 1 — harness neutrality

### The problem, measured rather than assumed

Before any of this, the exam was inspected to find what actually bound it to Grok. In 738
lines of `_intent_synthesis_exam.py` there was exactly **one** contestant-specific line —
`CANDIDATE = ModelIdentity(provider="xai", model="grok-4.7")` — used in exactly two places,
both identity checks inside `score_global_gates`. Every substrate builder and every
semantic scorer was already neutral.

That finding chose the design. A "thin OpenAI wrapper" would have had to duplicate
`score_global_gates`, because the contestant was baked into it — duplicating a load-bearing
gate that the 42 offline controls attack, leaving the copy unattacked and free to drift. A
second contestant is not a reason to own a second set of gates.

### What changed

**The contestant is now an input, not an assumption.**

```python
def score_global_gates(observation: ExamObservation, *, candidate: ModelIdentity) -> None
```

Required keyword, **no default**. A default would silently favour whichever model was
certified first: the second contestant's runner would either fail every call or quietly
inherit Grok's identity. Each runner now names its own contestant, and the shared module
holds none.

**Evidence is per-contestant.** `tests/certification/evidence/<provider>/<model>/` with
`measurements.json` and `case_a_ledger.json`. Previously both artifacts were single
hardcoded, git-tracked paths, so an OpenAI run would have rewritten Grok's committed
certification evidence in place — the one thing a certification system must never permit.
Grok's files were moved with `git mv` and are byte-identical.

**The failure taxonomy is explicit.** Four situations that a generic assertion used to
flatten into "the model failed":

| situation | category |
|---|---|
| the call never produced an answer | `INCOMPLETE: TRANSPORT FAILURE` |
| the certification's own output guard bound the call | `INCOMPLETE: HARNESS LIMIT` |
| a real response that broke the output contract | `NOT CERTIFIED: PROTOCOL/TASK FAILURE` |
| a typed response failing the semantic scorers | `NOT CERTIFIED: MODEL/TASK FAILURE` |

The first two are not verdicts about the model, and deliberately do not subclass
`AssertionError` so no `except` clause can absorb them as test failures.

**Replay is contestant-neutral and bombs every provider.** The suite discovers ledgers
under `evidence/*/*/` and derives the expected author from the path, so a new contestant is
enrolled by existing rather than by editing the test. The bomb covers `ModelRuntime.execute`
as the universal chokepoint plus every installed adapter, discovered by walking the adapters
package. A bomb that covered only xAI would have let an OpenAI ledger reach the OpenAI
client and still pass — quietly retiring a Foundry invariant at the exact moment a second
provider arrived.

### `max_output_tokens` is a guard, not the exam

Ruling R4, and the reason MR6 needed it: the number means different things per provider. For
xAI it bounds visible output; for OpenAI reasoning models it covers **reasoning tokens as
well**. Grok used 104–142 visible tokens against a 2000 bound — never remotely binding. The
same 2000 applied to Astra at `effort=high` could bind during reasoning and produce an
`incomplete` response that the old runner would have surfaced as an opaque "no model result
was captured" assertion, indistinguishable from incompetence.

So the guard is now classified as transport safety, predeclared per contestant, and required
to be non-binding. Two independent checks enforce that: the error classifier recognises a
truncation signal, and `assert_guard_was_not_binding` separately proves the run never
approached the bound. A run can otherwise pass every scorer while sitting one verbose answer
away from a false "not certified".

Astra's predeclared guard is **16000**; Grok's stays **2000**, unchanged.

### Telemetry stays honest

OpenAI reports no dollar cost and no finish reason *by design*, and its adapter refuses to
invent either. No gate ever required them — verified across the whole suite — so nothing
needed relaxing. What was added is the control that pins it: unreported telemetry must score
exactly like reported telemetry, so that no future change can turn `cost_usd=None` into a
failure whose only cure is fabricating `cost_usd=0` or `finish_reason="stop"`. Aggregates
carry `known_cost_samples` / `unknown_cost_samples` rather than a total that silently means
"free".

### Verification

Semantic byte-identity is diff-proved by AST: all five substrate builders and all five case
scorers are byte-identical, and `score_global_gates` is the only changed definition in the
module. 65 offline certification tests. 12 mutation controls on the new neutrality seams,
all killed.

One of those mutations mattered: deleting the runner's call to the classifier initially
**survived**, because the classifier was tested in isolation while nothing exercised
`run_attempt` itself offline. That flattening would have been discovered during a billed
live run — the one place it must never be discovered. Three controls now drive the real
runner with a provider that fails at the transport seam, so the wiring is asserted without a
network or a credential.

### Checkpoint-1 repair: a structured cause beats message text

Independent review found a real classification hole before any billed run, and it was the
expensive kind — one that only misfires when it matters.

MR5's frozen adapter catches both of the SDK's truncation errors and raises a single
`ModelProtocolError` reading *"OpenAI stopped the response before the requested structure
was complete"*. That sentence names no reason, and it is byte-identical for a length cutoff
and a content filter. The original classifier matched on message text, so a call truncated
by the certification's own 16,000-token guard would have been recorded as `NOT CERTIFIED:
PROTOCOL/TASK FAILURE` — blaming the contestant for the harness's bound, on a live run,
with a verdict that would have looked entirely plausible.

Classification now reads the preserved `__cause__`, which is the provider's own account of
why it stopped rather than the adapter's summary:

| cause | category |
|---|---|
| `openai.LengthFinishReasonError` | `INCOMPLETE: HARNESS LIMIT` |
| `openai.ContentFilterFinishReasonError` | `NOT CERTIFIED: PROTOCOL/TASK FAILURE` |
| no structured cause, reason in text | textual fallback, structured signals first |
| anything else | `NOT CERTIFIED: PROTOCOL/TASK FAILURE` |

Only `__cause__` is followed, never `__context__`: an implicit context can carry an
unrelated exception that merely happened to be in flight, and misreading one of those as a
truncation signal would be worse than having no signal at all. The chain is walked to any
depth, so a wrapper between adapter and SDK cannot hide the signal. Adding a provider later
is a row in the table, not another branch.

The frozen adapter was **not** changed to emit a better message. The certification harness
adapting to the provider's real exception shape is the correct direction; editing certified
production code so a test can read it more easily is not.

Seven further mutation controls cover this seam — cause inspection removed, the table rows
swapped, the chain walk truncated, the fallback deleted, and text made to win over a real
cause — and the length-cutoff case is driven through the real `run_attempt`, not the
classifier alone, so the Checkpoint-1 mutation-survival problem is not repeated.

### Checkpoint-1 repair: the guard needs headroom, not just slack

Rejecting only `high_water >= guard` meant a run finishing at 15,999 of 16,000 passed with
six tokens to spare. Nothing would have been truncated, every answer intact — and the next
attempt would have been one verbose response away from a different verdict, decided by our
own artificial bound rather than by Intent competence. A check that only catches exact
saturation is not the independent headroom assertion it was described as.

A certification run may now use at most **80% of its output guard** — at least 20% headroom.
For Astra's predeclared 16,000 that is a ceiling of **12,800**.

| high water (guard 16,000) | outcome |
|---|---|
| 12,000 / 12,800 | pass |
| 12,801 / 15,999 | `INCOMPLETE: HARNESS HEADROOM` |
| 16,000 | `INCOMPLETE: HARNESS LIMIT` |

`HarnessHeadroomExhausted` is a separate category from `HarnessLimitReached` because the
situations differ: one truncated an answer, the other did not. Both are `CertificationIncomplete`
and neither subclasses `AssertionError`, so no `except` clause can absorb either as a model
verdict.

Two details are deliberate. The threshold was **locked before any live contestant telemetry
existed**, so it can never be chosen — or quietly widened — to make a particular run pass; a
headroom failure requires a fresh fifteen-call run under a wider guard, never a re-reading of
the run that already happened, since raising the bound after seeing the numbers would make
the threshold a function of the result it is meant to judge. And the comparison is integer
arithmetic (`high_water * 100 > guard * 80`) rather than `guard * 0.8`, because 0.8 is not
exactly representable and the 12,800 boundary would otherwise be decided by rounding.

Headroom is measured on output tokens only; input is thousands of prompt tokens with no
bearing on an output bound. Grok's certified run is unaffected: 142 against a 2,000 guard is
7.1% utilisation.

Eight mutation controls cover this seam — the check deleted, the threshold widened so 15,999
passes, the comparison inverted, headroom measured on input tokens, an off-by-one, the float
boundary reintroduced, high water taken as `min`, and the category downgraded to an
`AssertionError`.

## Checkpoint 2 — attempt 1: INCOMPLETE (transport failure)

The authorized single run was executed against the frozen contestant, verified before the
first call: prompt SHA256 `af49dbd3…` computed live from source and agreeing with both the
declared constant and the brief, policy `intent-synthesis.slice1` /
`intent-synthesis-runtime-v1`.

**14 of 15 calls succeeded. Case D attempt 3 raised `ModelProviderError`.**

```
httpcore2.ReadTimeout -> httpx2.ReadTimeout -> openai.APITimeoutError
    -> ModelProviderError -> TransportFailure
```

**Verdict: `MR6 CERTIFICATION RUN INCOMPLETE: TRANSPORT FAILURE`.** No retry, no resume from
the missing attempt, no change to the guard, and no reinterpretation of fourteen passes as
certification.

This is the case the Checkpoint-1 taxonomy was built for. Before that work, a
`ModelProviderError` inside `_run_attempt` was caught by a generic `except Exception`,
recorded as a governance rejection, and then surfaced as `no model result was captured` —
an opaque assertion under a semantic test name. It would have been entirely natural to read
"Case D attempt 3 failed" as Astra inventing a choice between seven and thirty days, which
is the single most consequential thing Case D exists to detect. The run instead stopped with
the fault named as transport, and nothing about Astra's competence was measured or impugned
on that attempt.

### What was and was not written

`measurements.json` was never written: the completeness assertion fired before the writer,
so no fourteen-call baseline was fabricated. The Case A ledger *had* been written when that
case passed, and it was removed — a genuine Astra-authored ledger from a run that did not
complete would have auto-enrolled `openai/gpt-6-astra` in the replay suite and stood in the
evidence tree looking like certification evidence that does not exist. Grok's record is
byte-identical and untouched.

No certification document was created. There is nothing to certify.

### One observation for the next authorization

The proximate cause was our own predeclared 120-second read bound expiring. From total wall
clock (294.6s for the run, 120s of it the timed-out call) the other fourteen calls averaged
roughly 12.5 seconds, so the timeout is not systematically marginal for this task — D3 looks
like an outlier stall rather than a bound set too tight. That figure is an inference from
aggregate timing, not a per-call measurement, because the measurement artifact was correctly
never written.

Worth deciding before the next run: the headroom law protects the **output-token** guard but
has no equivalent on the **time** axis. A run that finished every call at 119 of 120 seconds
would pass today, for the same reason a run at 15,999 of 16,000 output tokens once would
have. The two bounds are the same kind of artificial certification limit.

## Checkpoint 2 — the certification run (not yet performed)

Only after Checkpoint 1 is accepted: add the Astra live runner, verify the frozen prompt
digest and policy version before the run, run A–E × 3 = 15 calls exactly once, capture
independent evidence, replay the fresh ledger under provider bombs, and generate the
certification record mechanically from the artifact.

Frozen throughout: the Intent prompt, policy id/version, structured output schema, semantic
cases, scorers, task/tier, `reasoning_effort=high`, and all eight production paths.
