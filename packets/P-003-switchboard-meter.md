# Packet P-003 — Switchboard Meter: Tokens and Cost per Tagged Call

**Department:** Coding Floor
**Wave:** 2 (builds on P-002)
**Language:** Python 3.12
**Architecture context:** Design doc §12.1. P-001 built the gate, P-002 the routing. P-003 makes every call metered: token counts and cost, attached to the call's Foundry tags, appended to a ledger file. This completes the Switchboard. (Database-backed metering is a future packet; this packet writes JSONL — one JSON record per line, append-only.)

## One job

After a successful routed call, extract token usage from the provider response, compute its cost, build a `MeterRecord` carrying the call's tags, and append it as one JSON line to a meter ledger file. Plus one ruled fix from the P-002 review.

## Cortex ruling applied (S1 ticket from P-002 review)

- **Lazy import:** `router.py` currently imports `litellm` at module level, costing ~6s on every import. Move the import inside `route_call`, in the branch where `completion_fn is None`. Module-level import of litellm is now FORBIDDEN.

## Dictionary (P-001/P-002 names unchanged; new names below)

| Concept | Name |
|---|---|
| Token usage block | `Usage` (fields: `prompt_tokens: int`, `completion_tokens: int`, `total_tokens: int`, `cost_usd: float \| None`) |
| One meter entry | `MeterRecord` (fields: `tags: CallTags`, `model_used: str`, `usage: Usage`, `recorded_at: datetime`) |
| The ledger writer | `MeterLedger` |
| Its append method | `MeterLedger.record(record: MeterRecord) -> None` |
| Its file path field | `MeterLedger.path` |
| Cost function parameter | `cost_fn` (parameter on `route_call`) |
| Default meter file | `ledger/meter.jsonl` (path is always caller-supplied; this is the convention, not a hardcode) |

Also now official in the Dictionary (ratified from P-002 review): `ModelRegistry.resolve(role)`.

## Files to create or modify (each under 300 lines)

```
switchboard/
├── src/switchboard/
│   ├── __init__.py         — MODIFY: also export Usage, MeterRecord, MeterLedger
│   ├── meter.py            — NEW: Usage, MeterRecord, MeterLedger
│   ├── request.py          — MODIFY: SwitchboardResponse gains `usage: Usage`
│   └── router.py           — MODIFY: lazy litellm import; usage extraction; cost_fn; meter hook
└── tests/
    ├── test_meter.py       — NEW
    └── test_router.py      — MODIFY: extend fakes with usage; meter integration tests
```

`tags.py`, `test_tags.py`, `registry.py`, `test_registry.py`, `registry.toml` are FORBIDDEN to change — stamped.

## Pinned dependencies

NO new dependencies. `json`, `pathlib`, `datetime` from the standard library. Existing pins unchanged: `pydantic==2.11.7`, `litellm==1.97.0`, `pytest==8.4.1`, `hatchling==1.32.0`.

## Behaviour contract

1. `route_call(request, registry, completion_fn=None, cost_fn=None, meter=None) -> SwitchboardResponse`. Gate first, routing second — both unchanged.
2. **Usage extraction:** from the provider response's `usage` attribute (`prompt_tokens`, `completion_tokens`, `total_tokens` — the OpenAI/LiteLLM shape; the test fakes must mimic it). A response with no usable `usage` attribute → all three counts recorded as `0` (never a crash; the meter must not be able to kill a successful call).
3. **Cost:** when `cost_fn` is None, use `litellm.completion_cost` (lazy-imported, same branch pattern as `completion` — module-level import forbidden). Call it with the provider response. If it raises or returns an unusable value → `cost_usd = None`. A cost failure must NEVER fail the call — cost is best-effort, tokens are mandatory.
4. **Metering:** when `meter` is provided and the call succeeds, build a `MeterRecord` (tags from the request, `model_used` from the actual answering model — the fallback winner, not the primary — `usage`, and a UTC `recorded_at`) and call `meter.record(...)` AFTER the response is fully built. When `meter` is None, skip metering silently — the Switchboard works without a meter attached.
5. **`MeterLedger`:** constructed with a `path`. `record(...)` appends exactly one line: the record as JSON (pydantic's JSON serialization) + newline. Parent directories are created if absent. The file is opened in append mode per record — no state held between calls, so multiple processes appending stay safe at this stage.
6. **A meter write failure must not kill the call:** if `meter.record(...)` raises (disk full, bad path), the response is still returned. The failure is re-raised as a Python `warning` (warnings.warn), not an exception.
7. `SwitchboardResponse.usage` is always present on success — even with no meter attached (counts still extracted).
8. Failed calls (all fallbacks exhausted) are NOT metered in this packet — `ProviderCallError` behaviour is unchanged. (Metering failed attempts' partial costs is a future packet; note this in the file header of meter.py as a known scope boundary.)

## Tests that must pass (ALL offline)

test_meter.py:
- MeterLedger.record appends exactly one JSON line; a second record appends a second line (file has 2 lines, both parse as JSON)
- parent directory is created when absent (use tmp_path / "deep/nested/meter.jsonl")
- the written JSON round-trips: parsed line reconstructs into a MeterRecord with equal tags, model_used, and usage
- Usage rejects negative token counts (pydantic validation, ge=0)

test_router.py (all P-002 tests keep passing; add):
- successful call with fake usage (e.g. 100/50/150) and fake cost_fn returning 0.0042 → response.usage carries exactly those numbers and cost_usd=0.0042
- fake response without a usage attribute → counts are 0/0/0, cost_usd is None, call still succeeds
- cost_fn raising → cost_usd is None, call still succeeds
- with a MeterLedger on tmp_path → after the call, the file contains one record whose tags/model_used match the request; with meter=None → no file is written
- fallback winner is metered: primary fake raises, fallback answers → MeterRecord.model_used is the fallback model
- a meter whose record() raises → route_call still returns the response, and a warning was raised (pytest.warns)
- module-level import check: `import switchboard.router` must not import litellm (assert "litellm" not in sys.modules after a fresh import in a subprocess, OR verify via importlib that router's module namespace has no litellm binding — either mechanism is acceptable, implemented with the standard library)

## Forbidden

- No changes to stamped files (tags.py, test_tags.py, registry.py, test_registry.py, registry.toml).
- No module-level litellm import anywhere.
- No database code, no SQL — JSONL only in this packet.
- No network in tests, no keys anywhere.
- No new dependencies.
- No files outside `switchboard/` and `ledger/`.
