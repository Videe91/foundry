"""Packet: P-009.5 + R-028 — matrix rendering and the run artifact.

One job: turn matrix rows into a readable grid and append them to the
append-only run ledger.

Split from smoke_matrix.py under the R-017 precedent when R-028's UNAVAILABLE
cell and bounded retry pushed that file past the 300-line ceiling. Per R-026 the
split inherits its parent's map entries.

Version: 0.11.1
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from smoke_matrix_columns import COLUMNS


def render_matrix(rows: list[MatrixRow]) -> str:
    """The grid, plus a numbered footnote for every failure.

    A FAIL cell carries up to 80 characters of provider error, which would set
    the width of every column and stop the grid being a grid. The cell shows a
    numbered marker instead and the full text is listed underneath — readable,
    and nothing is lost.
    """
    display: dict[tuple[str, str], str] = {}
    notes: list[str] = []
    for row in rows:
        for column in COLUMNS:
            cell = row.cells.get(column, "")
            if cell.startswith("FAIL("):
                notes.append(f"  [{len(notes) + 1}] {row.model} {column}: {cell}")
                display[(row.model, column)] = f"FAIL[{len(notes)}]"
            else:
                display[(row.model, column)] = cell

    widths = {
        column: max([len(column)] + [len(display[(r.model, column)]) for r in rows])
        for column in COLUMNS
    }
    model_width = max([len("model")] + [len(row.model) for row in rows])

    header = "  ".join(
        ["model".ljust(model_width)] + [c.ljust(widths[c]) for c in COLUMNS]
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            "  ".join(
                [row.model.ljust(model_width)]
                + [display[(row.model, c)].ljust(widths[c]) for c in COLUMNS]
            )
        )
    total = sum(row.cost_usd for row in rows)
    unpriced = [row.model for row in rows if not row.cost_known]
    lines.append("")
    summary = f"{len(rows)} models swept. Total cost: ${total:.6f}"
    if unpriced:
        # The total is a floor, not a figure — say so rather than let it read
        # as the whole bill.
        summary += (
            f" from {len(rows) - len(unpriced)} priced models; "
            f"{len(unpriced)} unpriced, actual spend is higher"
        )
    lines.append(summary)
    if notes:
        lines.append("")
        lines.append(f"failures ({len(notes)}):")
        lines.extend(notes)
    return "\n".join(lines)


def append_matrix_artifact(grid: str, path: Path) -> None:
    """Append this run to the dated artifact ledger, creating it if absent."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    if not path.exists():
        path.write_text(
            "# Matrix runs\n\nAppend-only. Each entry is one `smoke.py --matrix` "
            "sweep: every registry model against every attachment kind and the "
            "two-call cache demo. Cache values are OBSERVED, never asserted.\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {stamp}\n\n```\n{grid}\n```\n")
