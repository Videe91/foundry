"""Packet: P-016 — Research Both Ways: the sweep command.

One job: `foundry research <slug>` — run the market sweep on a completed
interview and show the founder what the market says back.

Version: 0.2.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WORKING = (
    "Researching the market. This searches the web and takes a while — "
    "nothing is streamed until it is done."
)
ACKNOWLEDGED_AT_SIGNING = (
    "Challenges are acknowledged at signing (P-017)."
)


def render_summary(findings: Any, paths: dict[str, Path]) -> str:
    """What the founder reads when the sweep returns."""
    lines = [
        "",
        f"  players found: {len(findings.players)}",
        f"  table stakes : {len(findings.table_stakes)}",
        f"  possible edge: {len(findings.edge)}",
        "",
    ]
    if findings.challenges:
        lines.append(f"  {len(findings.challenges)} challenge(s) to your intent:")
        for challenge in findings.challenges:
            lines.append(f"    - {challenge.claim}  →  presses on: {challenge.against}")
    else:
        lines.append("  0 challenges. Stated reason:")
        lines.append(f"    {findings.no_challenges_because}")
    lines += [
        "",
        f"  findings : {paths['json']}",
        f"  report   : {paths['md']}",
        f"  expires  : {findings.expires_at.isoformat()}",
        "",
    ]
    return "\n".join(lines)


def start(slug: str, root: Path | None = None, route: Any = None,
          printer: Any = print) -> int:
    """Compose the researcher and run one sweep."""
    import workspace
    from intent.research import ResearchError, findings_path, report_path, run_research
    from switchboard.registry import load_registry
    from workspace import MeterRouter

    from foundry_cli.brains import Brains
    from foundry_cli.session import _registry_path, open_or_create, receipt_line

    project, created = open_or_create(slug, root, workspace)
    printer(f"=== RESEARCH: {slug} ({'created' if created else 'existing'}) ===")
    if created:
        printer("  (a project with no interview — nothing to research yet)")

    registry = load_registry(_registry_path(project))
    meter = MeterRouter(
        lambda pid: project.meter_path if pid == slug else None,
        default_path=project.meter_path,
    )
    from foundry_cli.session import ProgressLine

    progress = ProgressLine(printer)
    brains = Brains(slug=slug, registry=registry, meter=meter, route=route,
                    project=project, on_waiting=progress.begin,
                    on_ready=progress.end)

    printer(WORKING)
    try:
        findings = run_research(project, brains.researcher)
    except ResearchError as exc:
        printer(f"\n{exc}")
        return 1

    printer(render_summary(findings, {
        "json": findings_path(project), "md": report_path(project)
    }))
    if brains.receipts:
        printer(receipt_line(brains.receipts))
    printer(ACKNOWLEDGED_AT_SIGNING)
    return 0
