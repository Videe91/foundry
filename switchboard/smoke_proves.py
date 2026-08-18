"""Packet: P-007 — Family Two: OpenAI Adapter.

One job: the smoke run's demonstration phases — roles, cache, attachments, and
streaming — driven once per provider family present in the registry.

Split from smoke.py under the R-017 precedent so both stay under the ceiling.
Prescribes no role→model choices (R-012); it reads the registry and demos what
is there.

Version: 0.7.0
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from smoke_debug import (
    Recorder,
    cache_minimum_for,
    debug_on,
    print_cache_diagnostics,
    print_role_system_check,
)
from smoke_families import (cache_note_for, demo_role_for, families_in,
                            family_has_adapter, family_of)
from smoke_fixtures import write_attachment_fixtures
from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry
from switchboard.request import Attachment, Message, SwitchboardRequest
from switchboard.router import route_call
from switchboard.tags import CallTags

SMOKE_PROJECT = "foundry-smoke"
SMOKE_DEPARTMENT = "adversarial"
EXCLUDED_FROM_PROVE = ("default", "architect_max")

# A fixed block, repeated to clear Anthropic's minimum cacheable prefix size.
# Identical on every call by construction — that is what makes it cacheable.
_CACHE_PARAGRAPH = (
    "Foundry is a factory with separated authority. Intent states the goal, "
    "Cortex decides the architecture, Planning issues packets, the coding "
    "floor builds strictly inside a declared scope, and Verification approves "
    "or rejects without ever seeing the builder\'s reasoning. Decisions descend "
    "from the highest applicable layer and are never made quietly below it. "
)
CACHE_SYSTEM_BLOCK = _CACHE_PARAGRAPH * 60


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
    print(f"  {model}: {cache_note_for(family_of(model))}")
    if family_of(model) == "anthropic":
        print(f"  prefix ~{prefix_tokens(model)} tokens vs minimum {cache_minimum_for(model)} (T-002)")
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
        # Lazy: dump_usage is Dictionary-assigned to smoke.py, which imports
        # this module — a module-level import would close the cycle (R-008).
        from smoke import dump_usage

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


def prove_families(
    registry: ModelRegistry,
    meter: MeterLedger,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> None:
    """Run the cache and attachment demos once per family in the registry."""
    for family in families_in(registry):
        role = demo_role_for(registry, family)
        if role is None:
            continue
        print(f"\n--- family: {family} (demo role: {role}) ---")
        prove_cache(registry, meter, role, completion_fn, cost_fn)
        if family_has_adapter(registry, family):
            prove_attachments(registry, meter, role, completion_fn, cost_fn)
        else:
            print(f"\n=== PROVE 3: ATTACHMENTS ===\n  [skip] {family}: "
                  "no family adapter — attachments unsupported")
