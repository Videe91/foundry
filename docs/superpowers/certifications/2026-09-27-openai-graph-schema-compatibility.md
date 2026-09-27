# OpenAI Structured Outputs compatibility: IE3 graph-answer wire schema

```
kind:       SCHEMA TRANSPORT COMPATIBILITY PROBE (not a model certification)
result:     ACCEPTED; trailing-newline boundary EXCLUDED (resolved)
provider:   openai (model endpoint gpt-6-astra, reasoning high / standard)
date:       2026-09-27
code:       a0fccc7
evidence:   tests/certification/evidence/_compatibility/openai/schema_probe.json
probe:      tests/integration/test_openai_graph_schema_probe_live.py
            (opt-in: OPENAI_API_KEY + RUN_LIVE_OPENAI_SCHEMA_PROBE=1; 2 calls)
```

| | |
|---|---|
| canonical graph-answer schema | `6b64d27457665492c887ec10c1ed78e3ba43373dbfe7eefbeba1b03169d93494` |
| OpenAI wire schema | `7b8257300ee6c18fa0d772ffd53cf354bb23a773d25e0dabff91076209249afa` |
| wire compiler | `foundry.openai-structured-outputs.v1` |

## What was established

1. **OpenAI accepts the compiled schema.** The earlier refusal (`400 invalid_json_schema`,
   "'oneOf' is not permitted") does not recur. The wire contains no `oneOf`.
2. **Nested `anyOf` is accepted** in all nine union positions: `GraphRef`, `GraphNodeProposal`
   and the seven two-state replaceable node families.
3. **`discriminator` metadata is accepted.** It was retained unchanged, not removed on a guess.
4. **One structured answer passed end to end** through `OpenAIModelProvider` and was validated
   by `IntentGraphDraftPayload` (outcome `ACCEPTED_AND_VALIDATED`).

## Regex boundary: resolved (the trailing newline is excluded)

Pydantic and JSON Schema's ECMA semantics both refuse a `local_id` ending in a newline; Python's
`re` would accept one, so the offline tests validate `pattern` with ECMA semantics. Whether
OpenAI's `pattern` also refuses it needed provider evidence. A model returning `"a"` when asked
for `"a\n"` could not settle it, so two dedicated probes *force* the value instead of asking for
it (raw SDK, strict mode, `gpt-6-astra`, reasoning high/standard; evidence in
`tests/certification/evidence/_compatibility/openai/`).

**Probe 1: enum forcing (`pattern_boundary_probe.json`). Inconclusive, but informative.**

| Call | Schema of `value` | Result |
|---|---|---|
| C1 | `enum ["a\n"]` | 400: "\n is not allowed in string literals for structured outputs (strict=true)" |
| C2 | `enum ["a"]` + `LOCAL_ID_PATTERN` | completed, `"a"` |
| C3 | `enum ["A"]` + `LOCAL_ID_PATTERN` | 400: "enum value A does not validate against {... 'pattern': '^[a-z][a-z0-9_-]{0,63}$'}" |
| T | `enum ["a\n"]` + `LOCAL_ID_PATTERN` | 400: the same literal refusal as C1 |

A newline cannot be named in a strict-mode literal, so T was refused before the pattern was
consulted. C3 shows that OpenAI does evaluate the production `pattern`.

**Probe 2: length forcing (`pattern_length_probe.json`). Decisive.** The field is
`pattern "^a$"` with `minLength = maxLength = n`. For n = 2, the only string a Python- or PCRE-
style `$` admits is `"a\n"`; an end-of-input `$` (ECMA, RE2) admits none.

| Call | n | Admissible under ECMA `$` | Result |
|---|---|---|---|
| L1 | 1 | `"a"` | completed, `"a"` |
| L2 | 3 | none (in any dialect) | `incomplete` (`max_output_tokens`), no output |
| T | 2 | none (Python-style would admit only `"a\n"`) | `incomplete` (`max_output_tokens`), no output, identical to L2 |

OpenAI's constrained decoder found no admissible two-character string: `"a\n"` is not admitted
on the wire. The probe establishes *that* it is excluded, not which mechanism excludes it (end-
of-input `$`, or a refusal of raw control characters in strings). Either way the soundness
assumption holds for this boundary: the OpenAI wire does not admit a trailing-newline
`local_id` that Pydantic would refuse. Pydantic still validates every answer regardless.

## What this is not

No model was examined. No certification record was written, no exam case ran, no scorer was
consulted, and nothing is wired into normal Foundry execution. The 24-attempt GPT-6 Astra graph
certification has not been started.
