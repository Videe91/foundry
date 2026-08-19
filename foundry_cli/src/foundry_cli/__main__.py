"""Packet: P-016 — Research Both Ways.

One job: dispatch the command line.

    python -m foundry_cli intent <slug>
    python -m foundry_cli bakeoff <slug> --turns N
    python -m foundry_cli research <slug>

The pyproject registers a `foundry` console script pointing here, so
`foundry intent <slug>` works after an editable install.

Version: 0.2.0
"""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foundry", description="Foundry — the composition edge."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    interview = sub.add_parser("intent", help="run or resume an intent interview")
    interview.add_argument("slug", help="the project slug")
    interview.add_argument("--root", type=Path, default=None,
                           help="workspace root (default: FOUNDRY_WORKSPACE_ROOT)")

    trial = sub.add_parser("bakeoff", help="try three Interviewer brains, blind")
    trial.add_argument("slug", help="the project slug")
    trial.add_argument("--turns", type=int, default=6,
                       help="turns per candidate (default: 6)")
    trial.add_argument("--root", type=Path, default=None)

    sweep = sub.add_parser("research", help="sweep the market for a completed intent")
    sweep.add_argument("slug", help="the project slug")
    sweep.add_argument("--root", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "intent":
        from foundry_cli.session import start

        return start(args.slug, root=args.root)

    if args.command == "research":
        from foundry_cli.research_cmd import start as research_start

        return research_start(args.slug, root=args.root)

    from foundry_cli.bakeoff import run_bakeoff

    return run_bakeoff(args.slug, root=args.root, turns=args.turns)


if __name__ == "__main__":  # pragma: no cover - exercised by the console script
    raise SystemExit(main())
