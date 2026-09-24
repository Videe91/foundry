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

## Checkpoint 2 — the certification run (not yet performed)

Only after Checkpoint 1 is accepted: add the Astra live runner, verify the frozen prompt
digest and policy version before the run, run A–E × 3 = 15 calls exactly once, capture
independent evidence, replay the fresh ledger under provider bombs, and generate the
certification record mechanically from the artifact.

Frozen throughout: the Intent prompt, policy id/version, structured output schema, semantic
cases, scorers, task/tier, `reasoning_effort=high`, and all eight production paths.
