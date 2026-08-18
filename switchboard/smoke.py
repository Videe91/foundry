"""Packet: P-007 — Family Two: OpenAI Adapter.

One job: prove the Anthropic family end to end against the real API — ping
every registry model, then demonstrate roles, prompt caching, and attachments.

This is the ONLY file in the repo that spends money, and a human runs it by
hand. Nothing here is imported by library code under src/.

Version: 0.7.0
"""

from __future__ import annotations

import base64
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, load_registry
from switchboard.request import Attachment, Message, SwitchboardRequest
from switchboard.router import route_call
from smoke_families import is_priced
from smoke_proves import (  # re-exported: smoke.py stays the public surface
    EXCLUDED_FROM_PROVE,
    SMOKE_DEPARTMENT,
    SMOKE_PROJECT,
    prove_attachments,
    prove_cache,
    prove_families,
    prove_roles,
    prove_streaming,
)
from smoke_fixtures import write_attachment_fixtures
from smoke_debug import (
    Recorder,
    cache_minimum_for,
    debug_on,
    print_cache_diagnostics,
    print_role_system_check,
)
from switchboard.tags import CallTags

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = Path(__file__).resolve().parent / "registry.toml"
METER_PATH = PROJECT_ROOT / "ledger" / "meter.jsonl"

SMOKE_PROJECT = "foundry-smoke"
SMOKE_DEPARTMENT = "adversarial"
PING_MAX_TOKENS = 8
EXCLUDED_FROM_PROVE = ("default", "architect_max")
def load_env() -> None:
    """Load the project-root .env. Imported lazily: dotenv is a smoke extra."""
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv())


def dump_usage(response: Any) -> dict:
    """Every usage field name and value on a raw provider response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "__dict__"):
        return dict(vars(usage))
    return {"usage": repr(usage)}


# A fixed block, repeated to clear Anthropic's minimum cacheable prefix size.
# Identical on every call by construction — that is what makes it cacheable.
# T-002: 30 repeats measured ~1861 tokens, 187 SHORT of haiku's 2048 minimum,
# so Anthropic silently declined to cache. 60 repeats clears it with margin.
_CACHE_PARAGRAPH = (
    "Foundry is a factory with separated authority. Intent states the goal, "
    "Cortex decides the architecture, Planning issues packets, the coding "
    "floor builds strictly inside a declared scope, and Verification approves "
    "or rejects without ever seeing the builder's reasoning. Decisions descend "
    "from the highest applicable layer and are never made quietly below it. "
)
CACHE_SYSTEM_BLOCK = _CACHE_PARAGRAPH * 60

class PingResult(NamedTuple):
    """One model's reachability check."""
    model: str
    ok: bool
    seconds: float
    error: str | None
    priced: bool


def ping_model(
    model: str, completion_fn: Callable[..., Any] | None = None
) -> PingResult:
    """Send the smallest possible real call. Never raises — reports instead."""
    caller = completion_fn
    if caller is None:
        import litellm
        caller = litellm.completion
    priced = is_priced(model)
    started = time.monotonic()
    try:
        caller(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=PING_MAX_TOKENS,
        )
    except Exception as exc:
        return PingResult(model, False, time.monotonic() - started, str(exc), priced)
    return PingResult(model, True, time.monotonic() - started, None, priced)


def unique_models(registry: ModelRegistry) -> list[str]:
    """Every distinct model string in the registry, primaries and fallbacks."""
    seen: dict[str, None] = {}
    for route in registry.roles.values():
        for model in (route.model, *route.fallbacks):
            seen.setdefault(model, None)
    return list(seen)


def ping_registry(
    registry: ModelRegistry, completion_fn: Callable[..., Any] | None = None
) -> list[PingResult]:
    """Ping each unique model exactly once."""
    return [ping_model(model, completion_fn) for model in unique_models(registry)]


def print_ping_table(results: list[PingResult]) -> None:
    print("\n=== PING ===")
    for result in results:
        if not result.ok:
            print(f"  FAIL  {result.seconds:6.2f}s  {result.model}\n        {result.error}")
            continue
        note = "priced" if result.priced else "UNPRICED — update litellm pin"
        print(f"  OK    {result.seconds:6.2f}s  {result.model}  ({note})")


















def main() -> int:
    load_env()
    registry = load_registry(REGISTRY_PATH)
    results = ping_registry(registry)
    print_ping_table(results)
    if any(not result.ok for result in results):
        print("\nPING FAILURES — fix registry.toml, then re-run")
        return 1
    meter = MeterLedger(METER_PATH)
    prove_roles(registry, meter)
    prove_families(registry, meter)
    prove_streaming(registry, meter)
    print(f"\nDone. Meter records appended to {METER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
