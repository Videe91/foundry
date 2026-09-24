# Model Runtime — MR2: first real provider (xAI / Grok 4.7)

Spec: `docs/superpowers/specs/2026-09-24-model-runtime-design.md` §12a.
MR1 remains a completed measured slice; nothing in it is rewritten.

## Scope

Plug the first real provider into the certified Model Runtime without changing its
architecture and without migrating any existing domain integration.

## Files

```
src/foundry/adapters/model_runtime/__init__.py
src/foundry/adapters/model_runtime/xai.py          XAIModelProvider, XAI_PROVIDER_ID
tests/unit/adapters/model_runtime/_fake_xai.py     SDK double built on real protos
tests/unit/adapters/model_runtime/test_xai.py      36 tests
tests/integration/test_xai_model_runtime_live.py   opt-in live smoke
```

`src/foundry/model_runtime/` is unchanged except one additive boundary test asserting the
adapter lives in the adapter layer and is where the SDK belongs.

## Public shape

```python
XAIModelProvider(
    api_key: str,                        # construction state only; never in any contract
    reasoning_effort: ReasoningEffort = "high",
    default_timeout_seconds: float | None = None,
    client_factory: _ClientFactory | None = None,   # injectable transport seam
    monotonic: Callable[[], float] = time.perf_counter,
)
```

`provider_id == "xai"`. Satisfies `foundry.model_runtime.ports.ModelProvider`.

## MEASURED (MR2 complete)

**RED:** `ModuleNotFoundError: No module named 'foundry.adapters.model_runtime'`.
**Installed SDK:** `xai-sdk 1.19.0` (unchanged; no new dependency).

| concern | measured behaviour |
|---|---|
| message mapping | same order, same role, same content; `system`/`user`/`assistant` builders; no augmentation |
| statelessness | `store_messages=False`; no `conversation_id`, no `previous_response_id` |
| retries | `channel_options=[("grpc.enable_retries", 0)]` |
| tools | none — no `tools`, `tool_choice`, `search_parameters`, `agent_count`, `include` |
| structured output | `chat.parse(output_type)`; malformed output → `ModelProtocolError` with cause |
| provider identity | `response.proto.model`, never the request; empty → `ModelProtocolError` |
| substitution | adapter reports actual; MR1's runtime raises `ModelProtocolError` |
| reasoning effort | `high` by default, adapter configuration, **not** on the shared request |
| usage | `prompt_tokens`→`input_tokens`, `completion_tokens`→`output_tokens`, `cost_usd_from_usage`, measured `wall_clock_ms` |
| unknown telemetry | stays `None`; no-presence token defaults are not read as data |
| finish reason | preserved when reported; `None` when absent; never invented |
| timeout | per-call client construction so the request's timeout applies |
| max output tokens | mapped to the supported `max_tokens` |
| max cost | refused before network with a truthful `ModelRequestError` |
| one-call law | one `execute` → exactly one `chat.create` |

**Mutations: 16 applied, 16 killed.** Three initially survived and each exposed a real
gap: a missing-identity guard whose diagnostic was untested, an API-key leak path through
*pre-network* refusals that the transport-failure test did not cover, and — most
importantly — token counts being reported as `0` when unreported, which is the invented
telemetry the contract forbids. The third was a correctness fix, not a test fix.

**Live smoke: RUN and PASSED** against real `grok-4.7`, 3/3 consecutive runs.

```
output          answer=68 units='units'
provider/model  xai / grok-4.7          (provider-REPORTED, not echoed)
task/tier       EVALUATION / REASONER
input_tokens    1354
output_tokens   10
cost_usd        0.001202
wall_clock_ms   3776
finish_reason   REASON_STOP
credential in result JSON: False
```

This certifies **transport and protocol only**: a real credential reached a real model
through `ModelRuntime → XAIModelProvider` and returned a typed object with normalized
metadata. It makes no claim about answer quality, and Grok remains uncertified for
`INTENT_SYNTHESIS` — the smoke's registry certifies `EVALUATION` alone, which is the
minimum the transport proof needs.

**A defect the live run surfaced.** The first live attempt failed with
`ModelProtocolError: output could not be parsed`, which sent the investigation toward a
schema bug — while the raw SDK call succeeded immediately afterward. The cause was the
adapter wrapping *every* exception from `chat.parse` as a protocol failure, including
transport faults. `grpc.RpcError` now propagates so the runtime maps it to
`ModelProviderError`, preserving the distinction MR1's taxonomy exists for. A unit
regression pins it. This is precisely the failure mode §19 warns about, and only a live
call exposed it.

**Frozen:** historical xAI adapters, Intent ports and application unchanged, hashes
reported. MR1 suite green and not weakened.

## Not in MR2

IntentSynthesizer migration, Research Worker, Architecture Engine, Reasoning Orchestrator,
subagents, fallback, retry, BYOK, cost routing, worker-tier model, any other provider.
