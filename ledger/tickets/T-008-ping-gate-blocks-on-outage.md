# T-008 — The ping gate treated a provider outage as a configuration error

**From:** Live `smoke.py --matrix` run 2026-08-18
**Raised by:** Coding Floor
**Status:** RESOLVED — ruled 2026-08-18 under R-028's taxonomy.
**Severity proposed:** S1 (a healthy nine-model sweep could not run at all, and
the advice printed was wrong)

## Symptom

`python smoke.py --matrix` pinged nine models, found eight healthy, and refused
to run anything:

```
  FAIL    4.97s  anthropic/claude-opus-5
        litellm.InternalServerError: AnthropicError -
        {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"},
         "request_id":"req_011CeAbmeDVaLT7aKwzUkECd"}
  OK      2.61s  anthropic/claude-sonnet-5  (priced)
  ... seven more OK ...

PING FAILURES — fix registry.toml, then re-run
```

**There was nothing to fix in `registry.toml`.** `anthropic/claude-opus-5` is a
correct model ID that had been answering all day; Anthropic capacity was
saturated.

## Diagnosis

`ping_model` caught every exception into `ok=False`, and the gate blocked on any
not-ok result with a single fixed message:

```python
except Exception as exc:
    return PingResult(model, False, ..., str(exc), priced)   # smoke.py
...
if any(not result.ok for result in results):
    print("\nPING FAILURES — fix registry.toml, then re-run")
    return 1
```

So it could not tell **a wrong model ID** — which genuinely needs a registry fix,
and is exactly what caught `grok-4.1-fast` — from **a provider outage**, which
needs no fix at all.

**This is the same defect R-028 had just corrected, one layer earlier.**
`is_unavailable` was written for precisely this taxonomy and wired into the
matrix; the ping gate predates it and never received it. The matrix would have
rendered Opus-5 as `UNAVAILABLE` — it never got the chance, because the gate
returned 1 first. Fixing one instrument and not the other left the earlier,
more damaging copy of the bug in place.

## Ruling and fix

**Option 1 ruled: FAIL blocks, UNAVAILABLE warns and proceeds.**

- The capacity taxonomy moved out of `smoke_matrix.py` into a leaf module,
  `smoke_health.py`, so the ping gate and the matrix share **one** definition
  rather than agreeing by coincidence.
- `PingResult` gains `unavailable: bool`. The table prints `UNAVAIL … provider
  capacity, not config: …` instead of `FAIL`.
- The gate blocks only on `not ok and not unavailable`. A config failure still
  prints "fix registry.toml" and runs nothing.
- `report_unavailable` warns loudly, naming each affected role and whether a
  **reachable** fallback can cover it, or saying `NO reachable fallback; this
  role will fail` when none can:

```
[warning] 1 model(s) unavailable (provider capacity, not config):
  anthropic/claude-opus-5
    primary for 'architect' — will run on anthropic/claude-sonnet-5
Proceeding. Affected cells record UNAVAILABLE.
```

The run stays honest by construction: `UNAVAILABLE` matrix cells and the
`[fallback]` notices from R-028 both report what actually happened.

## Guards, and why they discriminate

- **The trio still blocks.** A parametrised test asserts that T-004's MIME
  rejection, T-006's pixel floor, and the bad `grok-4.1-fast` model ID all keep
  `unavailable=False`. Each was a real defect needing a real fix; a matcher
  generous enough to excuse them would wave defects through the gate this ticket
  exists to keep shut.
- **An outage proceeds, end to end.** `main([])` returns **0** with a synthetic
  overload on a role's primary, and all four PROVE phases run.
- **A config failure still returns 1** and no PROVE phase runs.
- **Silence when healthy.** `report_unavailable` prints nothing when every model
  answers — a warning on every run would be noise, not signal.
