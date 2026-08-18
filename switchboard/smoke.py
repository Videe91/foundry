"""Packet: P-006 — Attachments: Text Kind (.md / .txt).

One job: prove the Anthropic family end to end against the real API — ping
every registry model, then demonstrate roles, prompt caching, and attachments.

This is the ONLY file in the repo that spends money, and a human runs it by
hand. Nothing here is imported by library code under src/.

Version: 0.6.0
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


def ping_model(
    model: str, completion_fn: Callable[..., Any] | None = None
) -> PingResult:
    """Send the smallest possible real call. Never raises — reports instead."""
    caller = completion_fn
    if caller is None:
        import litellm
        caller = litellm.completion
    started = time.monotonic()
    try:
        caller(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=PING_MAX_TOKENS,
        )
    except Exception as exc:
        return PingResult(model, False, time.monotonic() - started, str(exc))
    return PingResult(model, True, time.monotonic() - started, None)


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
        status = "OK  " if result.ok else "FAIL"
        line = f"  {status}  {result.seconds:6.2f}s  {result.model}"
        print(line if result.ok else f"{line}\n        {result.error}")


def _smoke_request(role: str, user: str, system: str | None, **extra: Any) -> SwitchboardRequest:
    return SwitchboardRequest(
        tags=CallTags(
            project_id=SMOKE_PROJECT, department=SMOKE_DEPARTMENT, role=role
        ),
        messages=[Message(role="user", content=user)],
        system=system,
        **extra,
    )


def prefix_tokens(model: str) -> int:
    """Measured size of the cache prefix — the number T-002 turned on."""
    import litellm
    return litellm.token_counter(model=model, text=CACHE_SYSTEM_BLOCK)


def _maybe_record(
    completion_fn: Callable[..., Any] | None,
) -> tuple[Callable[..., Any] | None, Recorder | None]:
    """In debug mode, wrap the real caller so the request/response is visible."""
    if completion_fn is None and debug_on():
        recorder = Recorder()
        return recorder, recorder
    return completion_fn, None


def prove_roles(
    registry: ModelRegistry,
    meter: MeterLedger,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> list[Any]:
    """One real call per role, metered. Skips default and the escalation tier."""
    print("\n=== PROVE 1: ROLES ===")
    caller, recorder = _maybe_record(completion_fn)
    responses = []
    for role in registry.roles:
        if role in EXCLUDED_FROM_PROVE:
            continue
        response = route_call(
            _smoke_request(role, "Status?", "Reply with exactly: FOUNDRY ONLINE"),
            registry,
            caller,
            cost_fn,
            meter,
        )
        responses.append(response)
        print(f"  {role:14s} {response.model_used:38s} {response.content!r}")
        if recorder is not None:
            print_role_system_check(recorder, role)
    return responses


def prove_cache(
    registry: ModelRegistry,
    meter: MeterLedger,
    role: str = "floor_agent",
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> list[Any]:
    """Call one role twice with an identical long system block."""
    print("\n=== PROVE 2: CACHE ===")
    model = registry.resolve(role).model
    minimum = cache_minimum_for(model)
    print(f"  prefix ~{prefix_tokens(model)} tokens vs {model} minimum {minimum} (T-002)")
    print("  expected: call 1 creation > 0, call 2 cached > 0 (reported, not asserted)")
    caller, recorder = _maybe_record(completion_fn)
    responses = []
    for attempt in (1, 2):
        response = route_call(
            _smoke_request(role, "Reply with one word: ready", CACHE_SYSTEM_BLOCK),
            registry,
            caller,
            cost_fn,
            meter,
        )
        responses.append(response)
        usage = response.usage
        print(
            f"  call {attempt}: cached={usage.cached_tokens} "
            f"creation={usage.cache_creation_tokens} "
            f"prompt={usage.prompt_tokens}"
        )
    if recorder is not None:
        print_cache_diagnostics(recorder, dump_usage)
    return responses


def prove_attachments(
    registry: ModelRegistry,
    meter: MeterLedger,
    role: str = "floor_agent",
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> Any:
    """Send a tiny PNG, PDF, and markdown file, and ask what arrived."""
    print("\n=== PROVE 3: ATTACHMENTS ===")
    with tempfile.TemporaryDirectory() as directory:
        png_path, pdf_path, md_path = write_attachment_fixtures(directory)
        response = route_call(
            _smoke_request(
                role,
                "Name the three file types you received.",
                None,
                attachments=[
                    Attachment(kind="image", path=str(png_path)),
                    Attachment(kind="pdf", path=str(pdf_path)),
                    Attachment(kind="text", path=str(md_path)),
                ],
            ),
            registry,
            completion_fn,
            cost_fn,
            meter,
        )
    print(f"  {response.model_used}: {response.content!r}")
    return response


def prove_streaming(
    registry: ModelRegistry,
    meter: MeterLedger,
    role: str = "judge",
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> Any:
    """Stream one answer, printing deltas as they land, then the receipt."""
    print("\n=== PROVE 4: STREAMING ===")
    print("  ", end="", flush=True)
    def emit(delta: str) -> None:
        print(delta, end="", flush=True)
    response = route_call(
        _smoke_request(role, "Count from 1 to 10 slowly, one number per line.", None),
        registry,
        completion_fn,
        cost_fn,
        meter,
        emit,
    )
    usage = response.usage
    print(
        f"\n  receipt: {response.model_used} "
        f"tokens={usage.prompt_tokens}/{usage.completion_tokens} "
        f"cost={usage.cost_usd}"
    )
    return response


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
    prove_cache(registry, meter)
    prove_attachments(registry, meter)
    prove_streaming(registry, meter)
    print(f"\nDone. Meter records appended to {METER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
