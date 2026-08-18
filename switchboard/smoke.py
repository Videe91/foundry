"""Packet: P-004 — Family One: Anthropic Adapter.

One job: prove the Anthropic family end to end against the real API — ping
every registry model, then demonstrate roles, prompt caching, and attachments.

This is the ONLY file in the repo that spends money, and a human runs it by
hand. Nothing here is imported by library code under src/.

Version: 0.4.0
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
from switchboard.tags import CallTags

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = Path(__file__).resolve().parent / "registry.toml"
METER_PATH = PROJECT_ROOT / "ledger" / "meter.jsonl"

SMOKE_PROJECT = "foundry-smoke"
SMOKE_DEPARTMENT = "adversarial"
PING_MAX_TOKENS = 8
EXCLUDED_FROM_PROVE = ("default", "architect_max")

# A fixed block, repeated to clear Anthropic's minimum cacheable prefix size.
# Identical on every call by construction — that is what makes it cacheable.
_CACHE_PARAGRAPH = (
    "Foundry is a factory with separated authority. Intent states the goal, "
    "Cortex decides the architecture, Planning issues packets, the coding "
    "floor builds strictly inside a declared scope, and Verification approves "
    "or rejects without ever seeing the builder's reasoning. Decisions descend "
    "from the highest applicable layer and are never made quietly below it. "
)
CACHE_SYSTEM_BLOCK = _CACHE_PARAGRAPH * 30

# A 1x1 transparent PNG and a minimal one-page PDF, both inline constants so
# the smoke run needs no image or PDF library.
TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
    "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PDF_STREAM = b"BT /F1 24 Tf 20 100 Td (Foundry P-004) Tj ET"


def load_env() -> None:
    """Load the project-root .env. Imported lazily: dotenv is a smoke extra."""
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())


def tiny_pdf_bytes() -> bytes:
    """Build a minimal one-page PDF by hand — no library, no dependency."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length "
        + str(len(_PDF_STREAM)).encode("ascii")
        + b" >>\nstream\n"
        + _PDF_STREAM
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    for number, body in enumerate(objects, start=1):
        out += str(number).encode("ascii") + b" 0 obj\n" + body + b"\nendobj\n"
    out += b"trailer\n<< /Root 1 0 R /Size 6 >>\n%%EOF\n"
    return bytes(out)


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


def prove_roles(
    registry: ModelRegistry,
    meter: MeterLedger,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> list[Any]:
    """One real call per role, metered. Skips default and the escalation tier."""
    print("\n=== PROVE 1: ROLES ===")
    responses = []
    for role in registry.roles:
        if role in EXCLUDED_FROM_PROVE:
            continue
        response = route_call(
            _smoke_request(role, "Status?", "Reply with exactly: FOUNDRY ONLINE"),
            registry,
            completion_fn,
            cost_fn,
            meter,
        )
        responses.append(response)
        print(f"  {role:14s} {response.model_used:38s} {response.content!r}")
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
    print(f"  system block: {len(CACHE_SYSTEM_BLOCK.split())} words")
    print("  expected: call 1 creation > 0, call 2 cached > 0 (reported, not asserted)")
    responses = []
    for attempt in (1, 2):
        response = route_call(
            _smoke_request(role, "Reply with one word: ready", CACHE_SYSTEM_BLOCK),
            registry,
            completion_fn,
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
    return responses


def prove_attachments(
    registry: ModelRegistry,
    meter: MeterLedger,
    role: str = "floor_agent",
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> Any:
    """Send a tiny PNG and a tiny PDF, and ask what arrived."""
    print("\n=== PROVE 3: ATTACHMENTS ===")
    with tempfile.TemporaryDirectory() as directory:
        png_path = Path(directory) / "pixel.png"
        pdf_path = Path(directory) / "page.pdf"
        png_path.write_bytes(base64.b64decode(TINY_PNG_BASE64))
        pdf_path.write_bytes(tiny_pdf_bytes())

        response = route_call(
            _smoke_request(
                role,
                "Name the two file types you received.",
                None,
                attachments=[
                    Attachment(kind="image", path=str(png_path)),
                    Attachment(kind="pdf", path=str(pdf_path)),
                ],
            ),
            registry,
            completion_fn,
            cost_fn,
            meter,
        )
    print(f"  {response.model_used}: {response.content!r}")
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
    print(f"\nDone. Meter records appended to {METER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
