"""Packet: P-014 — Intent, Part Two: The Live Interview.

One job: run the same interview opening against three candidate Interviewers so
the human can decide which brain to give the role — on evidence, not taste.

**Blind by construction.** Candidate order is shuffled, transcripts are labelled
A/B/C, and the model mapping is revealed only at the end. Knowing which model is
speaking is exactly the thing that would corrupt the judgement, since the whole
question is how each one makes the human respond.

The bake-off decides nothing. It produces evidence; the registry edit stays the
human's under R-012.

Version: 0.1.0
"""

from __future__ import annotations

import random
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from intent import new_state, run_turn

from foundry_cli.brains import Brains

DEFAULT_CANDIDATES: tuple[str, ...] = (
    "anthropic/claude-sonnet-5",
    "openai/gpt-5.6-terra",
    "openai/gpt-5.6-luna",
)
LABELS: tuple[str, ...] = ("A", "B", "C")
DEFAULT_TURNS = 6


def candidates_for(registry_path: Path | None) -> tuple[str, ...]:
    """A `[bakeoff]` table in the project's registry, else the documented trio."""
    if registry_path is None or not Path(registry_path).is_file():
        return DEFAULT_CANDIDATES
    try:
        data = tomllib.loads(Path(registry_path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return DEFAULT_CANDIDATES
    listed = data.get("bakeoff", {}).get("interviewer_candidates")
    if isinstance(listed, list) and listed:
        return tuple(str(model) for model in listed)
    return DEFAULT_CANDIDATES


def shuffled(models: tuple[str, ...], rng: random.Random | None = None) -> list[str]:
    """Order the candidates so the human cannot infer identity from position."""
    order = list(models)
    (rng or random.Random()).shuffle(order)
    return order


def candidate_registry(registry: Any, model: str) -> Any:
    """A copy of the registry with the interviewer role pointed at one model.

    Built in memory. The bake-off never edits registry.toml — informing that
    edit is its whole purpose, and making it would be the opposite (R-012).
    """
    clone = registry.model_copy(deep=True)
    route = clone.roles["interviewer"]
    clone.roles["interviewer"] = route.model_copy(update={"model": model,
                                                          "fallbacks": []})
    return clone


def run_candidate(
    label: str, model: str, slug: str, registry: Any, opening: str, turns: int,
    reader: Any, printer: Any, route: Any = None, meter: Any = None,
) -> list[tuple[str, str]]:
    """One short real conversation. Throwaway state — never the interview's.

    The human answers live: a simulated bake-off is fiction, because the thing
    being judged is how each candidate makes a real person respond.
    """
    printer(f"\n=== CANDIDATE {label} ===")
    brains = Brains(slug=slug, registry=candidate_registry(registry, model),
                    meter=meter, route=route,
                    on_delta=lambda d: printer(d, end="", flush=True))
    state = new_state(slug)  # throwaway: never persisted, never loaded
    message = opening
    exchanges: list[tuple[str, str]] = []

    for turn_number in range(turns):
        brains.turn_number = turn_number + 1
        state, result = run_turn(state, message, brains.interviewer, brains.scribe)
        exchanges.append(("user", message))
        if result.complete:
            printer("\n(candidate reached a complete interview)")
            break
        exchanges.append(("interviewer", result.reply or ""))
        if turn_number == turns - 1:
            break
        try:
            message = reader("you> ")
        except (EOFError, KeyboardInterrupt):
            printer("\n(candidate cut short)")
            break
    return exchanges


def render(label: str, exchanges: list[tuple[str, str]]) -> str:
    lines = [f"### Candidate {label}", ""]
    for role, content in exchanges:
        lines.append(f"**{role}:** {content}")
        lines.append("")
    return "\n".join(lines)


def append_evidence(project: Any, body: str, stamp: str) -> Path:
    """Every transcript lands in the project's own evidence ledger."""
    path = Path(project.evidence_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f"\n## Interviewer bake-off — {stamp}\n\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(header + body)
    return path


def run_bakeoff(
    slug: str, root: Path | None = None, turns: int = DEFAULT_TURNS,
    route: Any = None, printer: Any = print, reader: Any = input,
    rng: random.Random | None = None, stamp: str | None = None,
) -> int:
    """The three-way trial, blind until the last line."""
    import workspace
    from switchboard.registry import load_registry

    from foundry_cli.session import _registry_path, open_or_create

    project, _created = open_or_create(slug, root, workspace)
    registry_path = _registry_path(project)
    registry = load_registry(registry_path)
    order = shuffled(candidates_for(registry_path), rng)

    printer(f"=== BAKE-OFF: {slug} — {len(order)} candidates, {turns} turns each ===")
    printer("You will talk to each in turn. They are unlabelled on purpose.\n")
    opening = reader("Describe your idea (the same one goes to all three):\n> ")

    when = stamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    body = ""
    for label, model in zip(LABELS, order):
        exchanges = run_candidate(label, model, slug, registry, opening, turns,
                                  reader, printer, route)
        body += render(label, exchanges)

    mapping = "\n".join(f"- Candidate {l}: `{m}`" for l, m in zip(LABELS, order))
    body += f"#### Mapping (revealed after the read)\n\n{mapping}\n"
    path = append_evidence(project, body, when)

    printer("\n=== THE REVEAL ===")
    printer(mapping)
    printer(f"\nTranscripts appended to {path}")
    printer("The registry edit is yours (R-012) — this is evidence, not a decision.")
    return 0
