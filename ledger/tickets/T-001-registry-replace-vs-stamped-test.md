# T-001 — P-004 orders registry.toml replaced while test_registry.py is stamped

**From:** P-004 (Family One: Anthropic Adapter)
**Raised by:** Coding Floor
**Status:** RESOLVED by R-014 — fix executed as a P-004 amendment, 2026-08-18.
**Severity proposed:** S1 (packet is internally contradictory; cannot be satisfied)

## The contradiction

P-004 states three things that cannot all be true:

1. `registry.toml` — **REPLACE** entirely with the Anthropic-only block.
2. `test_registry.py` is **FORBIDDEN to change** (stamped).
3. **"Full suite green."**

`test_registry.py` loads the real `switchboard/registry.toml` and asserts on its
*values*. Replacing the file fails three stamped assertions. Demonstrated
empirically, then reverted:

```
FAILED test_registry_file_parses_and_architect_resolves
  assert 'anthropic/claude-opus-5' == 'anthropic/claude-sonnet-4-6'
FAILED test_every_declared_role_is_present
  architect_max is a new role; the stamped set has four entries
FAILED test_unknown_role_resolves_to_default_entry
  AssertionError: assert 64000 == 1024
3 failed, 4 passed
```

## Floor action taken

`registry.toml` was **NOT replaced**. Every other part of P-004 was built and
the suite is green. Editing the stamped test to fit is forbidden; shipping a red
suite is forbidden. This is exactly the case Law rule 2 reserves for a ticket.

## The deeper defect (the reason this is worth a ruling, not just a fix)

R-012 — which this same packet asks to record — states that `registry.toml` is
**user configuration**, editable by the human at any time with no packet, build,
or stamp. A stamped test that asserts on that file's *values* contradicts R-012
directly: under R-012 any legitimate human config edit turns the suite red, and
the human has no authority to fix it because the test is stamped.

So the conflict is not really "this packet vs this test" — it is
**configuration-as-law leaking into the test suite**. Recommended ruling:

- `test_registry.py` should assert **structure and behaviour**, not values:
  that the shipped file parses, that every entry has `model`/`fallbacks`/
  `max_tokens` of the right types, that `resolve()` falls back to `default`,
  and that malformed entries raise. No literal model strings, no literal
  `max_tokens`.
- That makes the registry freely editable per R-012 without touching the suite,
  which is the whole point of R-012.
- Cortex must unstamp `test_registry.py` for one packet to make that change.

## Question for Cortex

Which does the floor do next?

- **(a)** Unstamp `test_registry.py`, rewrite it value-free per above, then
  replace `registry.toml`. Preferred — it fixes the class of problem.
- **(b)** Keep the test stamped and leave `registry.toml` as-is; the human edits
  the registry by hand under R-012 and accepts that the stamped test will then
  fail. Not recommended — it leaves a red suite as the steady state.
- **(c)** Something else.

---

## Resolution — R-014

Cortex ruled option (a). Recorded as **R-014**: tests on configuration files
assert STRUCTURE, never VALUES; config belongs to the human under R-012, and a
test that pins config values contradicts that ownership.

Executed as an amendment to P-004:

1. `test_registry.py` was unstamped for this packet only and rewritten to
   assert structure — the shipped registry parses, every entry has a non-empty
   `model`, list-of-string `fallbacks`, and positive integer `max_tokens`, and
   a `default` role exists. All resolution behaviour moved to synthetic TOML
   fixtures in `tmp_path`.
2. `registry.toml` was then REPLACED with the P-004 Anthropic block —
   verified byte-for-byte against the packet, with the R-004 header above it.
3. Full suite green at 65 passed.
4. The ruling's property was verified, not assumed: a simulated human config
   edit (model swapped, ceiling changed, cross-family fallback added) leaves
   the suite green. That is the outcome R-012 requires and the old stamped
   test prevented.

`test_registry.py` is re-stamped as of this build going green. **CLOSED.**
