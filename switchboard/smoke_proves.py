"""Packet: P-010 — Streaming by default, all families.

One job: the smoke run's demonstration phases — roles, cache, attachments, and
streaming — driven once per provider family present in the registry.

Split from smoke.py under the R-017 precedent so both stay under the ceiling.
Prescribes no role→model choices (R-012); it reads the registry and demos what
is there.

Version: 0.10.1
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from typing import Any

from smoke_debug import (
    Recorder,
    cache_minimum_for,
    debug_on,
    print_cache_diagnostics,
    print_role_system_check,
)
from smoke_families import (cache_expectation_for, cache_note_for,
                            cache_paragraphs_for, demo_role_for, families_in,
                            family_has_adapter, family_of)
from smoke_fixtures import write_attachment_fixtures
from switchboard.adapters import supported_kinds_for
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


def cache_block_for(family: str) -> str:
    """This family's cache-demo prefix, sized to its MEASURED minimum (T-007).

    There is deliberately no single CACHE_SYSTEM_BLOCK any more: one constant
    sized for one family is what let Gemini report zero hits for twelve calls
    while every test passed.
    """
    return _CACHE_PARAGRAPH * cache_paragraphs_for(family)


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
    return litellm.token_counter(model=model, text=cache_block_for(family_of(model)))


def _maybe_record(
    completion_fn: Callable[..., Any] | None,
) -> tuple[Callable[..., Any] | None, Recorder | None]:
    """In debug mode, wrap the real caller so the request/response is visible."""
    if completion_fn is None and debug_on():
        recorder = Recorder()
        return recorder, recorder
    return completion_fn, None


def note_if_not_primary(registry: ModelRegistry, role: str, model_used: str) -> None:
    """Say so out loud when a fallback answered instead of the role's primary.

    During the 2026-08-18 Opus-5 outage every `architect` call ran on Sonnet-5
    — correctly, and completely silently. The chain is supposed to absorb an
    outage; it is not supposed to hide which model actually did the work
    (R-028).
    """
    primary = registry.resolve(role).model
    if model_used != primary:
        print(f"  [fallback] {role}: {primary} did not answer — "
              f"{model_used} did. The receipt is for {model_used}.")


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
        note_if_not_primary(registry, role, response.model_used)
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
    """Call one role twice with an identical long system block.

    The block is sized per family (T-007): one shared constant let Gemini
    report zero hits for twelve calls while every test passed.
    """
    print("\n=== PROVE 2: CACHE ===")
    model = registry.resolve(role).model
    family = family_of(model)
    print(f"  {model}: {cache_note_for(family)}")
    print(f"  prefix ~{prefix_tokens(model)} tokens "
          f"vs minimum {cache_minimum_for(model)}")
    print(f"  expected: {cache_expectation_for(family)}"
          " (reported, not asserted)")
    caller, recorder = _maybe_record(completion_fn)
    responses = []
    for attempt in (1, 2):
        response = route_call(
            _smoke_request(role, "Reply with one word: ready", cache_block_for(family)),
            registry,
            caller,
            cost_fn,
            meter,
        )
        responses.append(response)
        note_if_not_primary(registry, role, response.model_used)
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
    """Send the attachment kinds this family accepts, and ask what arrived.

    Not every family takes all three: xAI's chat API documents text and image
    input only, and its adapter refuses `kind="pdf"` outright (P-009 contract
    4). Sending a refused kind would raise, so the demo asks the adapter what
    the family accepts and says out loud what it left behind.
    """
    print("\n=== PROVE 3: ATTACHMENTS ===")
    accepted = supported_kinds_for(registry.resolve(role).model) or ()
    with tempfile.TemporaryDirectory() as directory:
        png_path, pdf_path, md_path = write_attachment_fixtures(directory)
        by_kind = {"image": png_path, "pdf": pdf_path, "text": md_path}
        refused = [kind for kind in by_kind if kind not in accepted]
        if refused:
            print(f"  note: this family does not accept {', '.join(refused)}"
                  f" — sending {', '.join(k for k in by_kind if k in accepted)}")
        attachments = [
            Attachment(kind=kind, path=str(path))
            for kind, path in by_kind.items()
            if kind in accepted
        ]
        response = route_call(
            _smoke_request(
                role,
                f"Name the {len(attachments)} file types you received.",
                None,
                attachments=attachments,
            ),
            registry,
            completion_fn,
            cost_fn,
            meter,
        )
    print(f"  {response.model_used}: {response.content!r}")
    note_if_not_primary(registry, role, response.model_used)
    return response


def prove_streaming(
    registry: ModelRegistry,
    meter: MeterLedger,
    role: str = "judge",
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> Any:
    """Stream one answer, printing deltas as they land, then the receipt.

    Runs once per family (P-010). Streaming was live-proven on Anthropic only,
    and the default flip puts all four families on the streaming path — so
    every family's terminal-usage receipt is now an R-024 acceptance gate, not
    an assumption inherited from one provider.
    """
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
    note_if_not_primary(registry, role, response.model_used)
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
        prove_streaming(registry, meter, role, completion_fn, cost_fn)
