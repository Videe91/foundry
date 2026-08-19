"""Packet: P-012 — the meter learns addresses.

One job: prove the Switchboard end to end against the real API — ping every
registry model, then demonstrate roles, prompt caching, and attachments.

`--matrix` adds a per-MODEL sweep on top; `--project <slug>` files the receipts
in that project's own ledger. Both are additive: without them the run is
unchanged.

This is the ONLY file in the repo that spends money, and a human runs it by
hand. Nothing here is imported by library code under src/.

Version: 0.12.0
"""

from __future__ import annotations

import base64
import sys
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
from smoke_search import prove_search, prove_search_or_skip
from smoke_health import is_unavailable
from smoke_matrix import run_matrix
from smoke_proves import (  # re-exported: smoke.py stays the public surface
    set_tagged_project,
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
MATRIX_PATH = PROJECT_ROOT / "ledger" / "matrix-runs.md"
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


class PingResult(NamedTuple):
    """One model's reachability check.

    `ok=False` splits two ways (T-008). `unavailable` means provider capacity —
    nothing is misconfigured and there is nothing to fix in registry.toml.
    Anything else is a real failure: a wrong model ID, bad auth, a 4xx.
    """
    model: str
    ok: bool
    seconds: float
    error: str | None
    priced: bool
    unavailable: bool = False


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
        return PingResult(
            model, False, time.monotonic() - started, str(exc), priced,
            is_unavailable(exc),
        )
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
        if result.unavailable:
            print(f"  UNAVAIL {result.seconds:6.2f}s  {result.model}"
                  f"\n        provider capacity, not config: {result.error}")
            continue
        if not result.ok:
            print(f"  FAIL  {result.seconds:6.2f}s  {result.model}\n        {result.error}")
            continue
        note = "priced" if result.priced else "UNPRICED — update litellm pin"
        print(f"  OK    {result.seconds:6.2f}s  {result.model}  ({note})")


def report_unavailable(registry: ModelRegistry, results: list[PingResult]) -> None:
    """Warn loudly about capacity outages, naming who depends on each model.

    Ruled under T-008: an outage does not block the run. It must not pass
    quietly either — the operator needs to know which roles are affected and
    whether each can still run, because a role answered by its fallback is a
    different receipt from the one the registry describes.
    """
    down = [result.model for result in results if result.unavailable]
    if not down:
        return
    reachable = {result.model for result in results if result.ok}
    print(f"\n[warning] {len(down)} model(s) unavailable "
          "(provider capacity, not config):")
    for model in down:
        print(f"  {model}")
        for role, route in registry.roles.items():
            if route.model != model:
                continue
            usable = [f for f in route.fallbacks if f in reachable]
            if usable:
                print(f"    primary for '{role}' — will run on {usable[0]}")
            else:
                print(f"    primary for '{role}' — NO reachable fallback; "
                      "this role will fail")
    print("Proceeding. Affected cells record UNAVAILABLE.")


















def project_meter(slug: str, meter_path: Path) -> Any:
    """A meter that files this run's receipts in `slug`'s own ledger.

    Imported lazily and only here: a run without `--project` never touches the
    workspace package at all. The Switchboard does not depend on the Workspace
    — this is the seam being crossed by the caller, which is the only place it
    may be crossed (P-012).
    """
    workspace_src = PROJECT_ROOT / "workspace" / "src"
    if workspace_src.is_dir() and str(workspace_src) not in sys.path:
        sys.path.insert(0, str(workspace_src))
    from workspace import MeterRouter, create_project, open_project, workspace_root
    from workspace.factory import WorkspaceError

    root = workspace_root()
    try:
        project = open_project(slug, root=root)
        print(f"\n=== PROJECT: {slug} (existing) ===")
    except WorkspaceError:
        project = create_project(slug, slug, root=root)
        print(f"\n=== PROJECT: {slug} (created) ===")
    print(f"  receipts -> {project.meter_path}")

    set_tagged_project(slug)
    # The global ledger is the fallback, so a record that cannot be routed is
    # still filed somewhere — never dropped, and never written twice.
    return project.meter(), MeterRouter(
        lambda pid: project.meter_path if pid == slug else None,
        default_path=meter_path,
    )


def _project_flag(argv: list[str]) -> str | None:
    if "--project" not in argv:
        return None
    index = argv.index("--project")
    if index + 1 >= len(argv):
        raise SystemExit("--project needs a slug, e.g. --project my-app")
    return argv[index + 1]


def main(argv: list[str] | None = None) -> int:
    """The default run is untouched; --matrix and --project are additive."""
    args = sys.argv[1:] if argv is None else argv
    matrix = "--matrix" in args
    slug = _project_flag(args)
    load_env()
    registry = load_registry(REGISTRY_PATH)
    results = ping_registry(registry)
    print_ping_table(results)
    # Only a CONFIG failure blocks. A capacity outage warns and proceeds
    # (T-008): the run stays honest through UNAVAILABLE cells and the
    # [fallback] notices, and eight healthy models should not wait on one.
    if any(not result.ok and not result.unavailable for result in results):
        print("\nPING FAILURES — fix registry.toml, then re-run")
        return 1
    report_unavailable(registry, results)
    meter = MeterLedger(METER_PATH)
    project_ledger = None
    if slug is not None:
        project_ledger, meter = project_meter(slug, METER_PATH)
    if matrix:
        run_matrix(registry, unique_models(registry), meter, MATRIX_PATH)
        _report_destination(project_ledger)
        return 0
    prove_roles(registry, meter)
    # PROVE 4 runs inside prove_families now — one streamed call per family,
    # which is the R-024 acceptance gate for the P-010 default flip.
    prove_families(registry, meter)
    _report_destination(project_ledger)
    return 0


def _report_destination(project_ledger: Any) -> None:
    if project_ledger is None:
        print(f"\nDone. Meter records appended to {METER_PATH}")
        return
    count = len(
        [
            line
            for line in project_ledger.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    ) if project_ledger.path.exists() else 0
    print(
        f"\nDone. Receipts appended to {project_ledger.path} ({count} records)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
