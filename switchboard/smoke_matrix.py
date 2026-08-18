"""Packet: P-009.5 + R-028 — The Model Matrix.

One job: sweep EVERY model in the registry — primaries and fallbacks alike —
through each attachment kind and the two-call cache demo, and render one grid
of what each model did.

Per-family demos answer "does this family work". The matrix answers "does this
MODEL work", which is a different question the moment a human repoints a role
or leans on a fallback. Nothing here is asserted: cache values are OBSERVED
(R-014), and a kind the family never claimed to support is REFUSED by design,
not a failure.

Version: 0.10.1
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from smoke_families import family_of
from smoke_matrix_columns import KINDS, OK, REFUSED, UNAVAILABLE
from smoke_matrix_render import append_matrix_artifact, render_matrix
from smoke_fixtures import write_attachment_fixtures
from smoke_proves import _smoke_request, cache_block_for
from switchboard.adapters import supported_kinds_for
from switchboard.meter import MeterLedger
from switchboard.registry import ModelRegistry, RoleRoute
from switchboard.router import route_call

MATRIX_ROLE = "matrix"
ERROR_CHARS = 80
FALLBACK_MAX_TOKENS = 4096
RETRY_DELAY_SECONDS = 20.0

# Provider capacity, not model capability. Opus-5 spent 25 minutes in this state
# and rendered as five FAIL cells indistinguishable from "cannot do attachments"
# — which is what R-028 corrected. Matched on the provider's own words, since
# LiteLLM wraps the class name differently per path (MidStreamFallbackError when
# streaming, InternalServerError when blocking, for the identical condition).
_UNAVAILABLE_MARKERS = (
    "overloaded",
    "service unavailable",
    "internalservererror",
    "serviceunavailable",
    "capacity",
    "502",
    "503",
    "529",
)


def is_unavailable(exc: Exception) -> bool:
    """True when the provider could not serve us, whatever the model can do."""
    text = str(exc).lower()
    return any(marker in text for marker in _UNAVAILABLE_MARKERS)


class MatrixRow(NamedTuple):
    """One model's results, one cell per column."""

    model: str
    cells: dict[str, str]
    cost_usd: float


def _owning_route(registry: ModelRegistry, model: str) -> RoleRoute | None:
    """The first route that names this model, as primary or as fallback.

    max_tokens is inherited from it rather than invented — a ceiling is a
    human decision under R-012 and the matrix has no business picking one.
    """
    for route in registry.roles.values():
        if model == route.model or model in route.fallbacks:
            return route
    return None


def matrix_registry(registry: ModelRegistry, model: str) -> ModelRegistry:
    """A one-role registry pinning this exact model, with no fallbacks.

    No fallbacks: the matrix asks what THIS model does, and a silent hand-off
    to another model would make the grid a liar. No effort either — effort is
    orthogonal to attachment and cache capability, and inheriting a role's
    level across families could exceed a family ceiling (R-025) and inject a
    failure that says nothing about what this instrument measures.
    """
    route = _owning_route(registry, model)
    return ModelRegistry(
        roles={
            MATRIX_ROLE: RoleRoute(
                model=model,
                fallbacks=[],
                max_tokens=route.max_tokens if route else FALLBACK_MAX_TOKENS,
            )
        }
    )


def _attempt(call: Callable[[], Any]) -> tuple[Any, str | None]:
    """Run one probe, retrying ONCE on a provider-capacity error.

    One bounded retry, not a loop: a transient blip should not poison the grid,
    and a sustained outage should not stall a nine-model sweep behind it.
    Returns (result, cell) where exactly one is None.
    """
    try:
        return call(), None
    except Exception as exc:
        if not is_unavailable(exc):
            return None, _cell_error(exc)
    time.sleep(RETRY_DELAY_SECONDS)
    try:
        return call(), None
    except Exception as exc:
        return None, (UNAVAILABLE if is_unavailable(exc) else _cell_error(exc))


def _cell_error(exc: Exception) -> str:
    """A failure cell: never blank, never the whole traceback.

    The router wraps provider errors as "all models failed for role 'matrix':
    tried X; last error: ...". The row already names the model, so the wrapper
    would spend the whole 80-character budget repeating it — unwrap to the
    provider's own words.
    """
    text = str(exc)
    _, separator, tail = text.partition("last error: ")
    return f"FAIL({(tail if separator else text)[:ERROR_CHARS]})"


def probe_kind(
    registry: ModelRegistry,
    model: str,
    kind: str,
    path: Path,
    meter: MeterLedger,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> tuple[str, float]:
    """Send one attachment of one kind, and say what happened.

    A kind the family does not declare is REFUSED by design — xAI's pdf is the
    known case (P-009 contract 4), and a family with no adapter at all declares
    nothing. Neither is a failure, and neither costs a call.
    """
    from switchboard.request import Attachment

    supported = supported_kinds_for(model)
    if supported is None or kind not in supported:
        return REFUSED, 0.0

    response, cell = _attempt(
        lambda: route_call(
            _smoke_request(
                MATRIX_ROLE,
                "Name the file type you received.",
                None,
                attachments=[Attachment(kind=kind, path=str(path))],
            ),
            matrix_registry(registry, model),
            completion_fn,
            cost_fn,
            meter,
        )
    )
    if cell is not None:  # one model's failure never stops the sweep
        return cell, 0.0
    return OK, response.usage.cost_usd or 0.0


def probe_cache(
    registry: ModelRegistry,
    model: str,
    meter: MeterLedger,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> tuple[list[str], float]:
    """Two byte-identical calls, reporting observed cached/creation per call.

    OBSERVED, never asserted (R-014): Gemini's zero hits and xAI's constant
    128-token floor are open observations this instrument extends across every
    model rather than settling.
    """
    pinned = matrix_registry(registry, model)
    block = cache_block_for(family_of(model))
    cells: list[str] = []
    cost = 0.0
    for _call in (1, 2):
        response, cell = _attempt(
            lambda: route_call(
                _smoke_request(MATRIX_ROLE, "Reply with one word: ready", block),
                pinned,
                completion_fn,
                cost_fn,
                meter,
            )
        )
        if cell is not None:
            cells.append(cell)
            continue
        usage = response.usage
        cells.append(f"{usage.cached_tokens}/{usage.cache_creation_tokens}")
        cost += usage.cost_usd or 0.0
    return cells, cost


def matrix_row(
    registry: ModelRegistry,
    model: str,
    meter: MeterLedger,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> MatrixRow:
    """Every probe for one model. Never raises — a dead model is a row, not a stop."""
    cells: dict[str, str] = {}
    cost = 0.0
    with tempfile.TemporaryDirectory() as directory:
        by_kind = dict(zip(KINDS, write_attachment_fixtures(directory)))
        for kind in KINDS:
            cell, spent = probe_kind(
                registry, model, kind, by_kind[kind], meter, completion_fn, cost_fn
            )
            cells[kind] = cell
            cost += spent

    cache_cells, cache_cost = probe_cache(
        registry, model, meter, completion_fn, cost_fn
    )
    for column, cell in zip(("cache c1", "cache c2"), cache_cells):
        cells[column] = cell
    cost += cache_cost
    cells["cost"] = f"{cost:.6f}"
    return MatrixRow(model=model, cells=cells, cost_usd=cost)






def run_matrix(
    registry: ModelRegistry,
    models: list[str],
    meter: MeterLedger,
    artifact_path: Path,
    completion_fn: Callable[..., Any] | None = None,
    cost_fn: Callable[..., Any] | None = None,
) -> list[MatrixRow]:
    """Sweep every model, print the grid, and append it to the ledger."""
    print(f"\n=== MATRIX: {len(models)} models ===")
    rows = []
    for model in models:
        print(f"  probing {model} ...", flush=True)
        rows.append(matrix_row(registry, model, meter, completion_fn, cost_fn))

    grid = render_matrix(rows)
    print(f"\n{grid}")
    append_matrix_artifact(grid, artifact_path)
    print(f"\nMatrix appended to {artifact_path}")
    return rows
