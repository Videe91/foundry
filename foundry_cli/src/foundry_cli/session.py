"""Packet: P-014 — Intent, Part Two: The Live Interview.

One job: the interview loop — create or resume a project, prompt the founder,
run turns through the engine, and hand over honestly when the engine says the
interview is complete.

The signature ceremony is NOT here. This packet stops at the box summary and
says so out loud (P-015).

Version: 0.2.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from intent import completeness, load_state, new_state, run_turn
from intent.skeleton import CONVERSATIONAL_KEYS, INTERNAL_KEYS
from intent.skeleton import CONFIRMED

from foundry_cli.brains import Brains, ScribeParseError, attachment_for

PROMPT = "you> "
IDEA_PROMPT = "Describe your idea (a sentence or two is plenty):\n"
HANDOVER = (
    "Interview complete. The signature ceremony (Fire Exits check, play-back, "
    "and signing) arrives in P-015 — this interview is saved and will be "
    "picked up there."
)
RESUME_HINT = "Nothing is lost — run the same command to pick up where you stopped."


def open_or_create(slug: str, root: Path | None, workspace: Any) -> Any:
    """Reuse P-012's create-if-absent pattern rather than inventing another."""
    try:
        return workspace.open_project(slug, root=root), False
    except workspace.WorkspaceError:
        return workspace.create_project(slug, slug, root=root), True


def status_table(state: Any) -> str:
    """The boxes in plain words — what is settled and who settled it.

    Counts CONVERSATIONAL boxes only. Counting the reserved slot reported
    "1 of 8 complete" before the founder had said a word, which flatters the
    progress bar at the founder's expense (T-009 sweep).
    """
    done = completeness(state)
    width = max(len(key) for key in CONVERSATIONAL_KEYS)
    lines = [f"{'box'.ljust(width)}  {'status':<10} {'by':<12} complete"]
    lines.append("-" * len(lines[0]))
    for key in CONVERSATIONAL_KEYS:
        box = state.boxes[key]
        lines.append(
            f"{key.ljust(width)}  {box.status:<10} "
            f"{(box.proposed_by or '-'):<12} {'yes' if done[key] else 'no'}"
        )
    settled = sum(1 for key in CONVERSATIONAL_KEYS if done[key])
    lines.append("")
    lines.append(f"{settled} of {len(CONVERSATIONAL_KEYS)} boxes complete")
    if INTERNAL_KEYS:
        lines.append(
            f"(plus {len(INTERNAL_KEYS)} reserved internally: "
            f"{', '.join(INTERNAL_KEYS)} — not yours to answer)"
        )
    return "\n".join(lines)


def summary_table(state: Any) -> str:
    """The completion view: each box, one line of content, who confirmed it."""
    width = max(len(key) for key in CONVERSATIONAL_KEYS)
    lines = []
    for key in CONVERSATIONAL_KEYS:
        box = state.boxes[key]
        content = ", ".join(f"{k}={v}" for k, v in box.content.items())
        if len(content) > 60:
            content = content[:57] + "..."
        by = box.proposed_by if box.status == CONFIRMED else "unconfirmed"
        lines.append(f"{key.ljust(width)}  {content:<62} [{by}]")
    return "\n".join(lines)


def receipt_line(receipts: list[Any]) -> str:
    """Honest totals: never claim a figure that includes unpriced calls.

    The matrix rule (R-028 era), applied here: a total containing an unknown
    line item is not a total, so it is reported as a floor.
    """
    tokens = sum(getattr(r.usage, "total_tokens", 0) or 0 for r in receipts)
    costs = [getattr(r.usage, "cost_usd", None) for r in receipts]
    known = [c for c in costs if c is not None]
    if len(known) == len(costs):
        money = f"${sum(known):.4f}"
    else:
        money = f"at least ${sum(known):.4f} plus {len(costs) - len(known)} unpriced calls"
    return f"{len(receipts)} calls, {tokens} tokens, {money}"


class Session:
    """One interview at the terminal."""

    def __init__(self, slug: str, project: Any, brains: Brains,
                 state: Any, printer: Any = print, reader: Any = input) -> None:
        self.slug = slug
        self.project = project
        self.brains = brains
        self.state = state
        self.print = printer
        self.read = reader
        self.queued: list[Any] = []

    # --- in-conversation commands ------------------------------------------

    def handle_command(self, line: str) -> str:
        """Returns 'quit', 'handled', or 'not-a-command'."""
        if not line.startswith("/"):
            return "not-a-command"
        command, _, argument = line.partition(" ")
        if command == "/quit":
            return "quit"
        if command == "/status":
            self.print(status_table(self.state))
            return "handled"
        if command == "/attach":
            self._attach(argument.strip())
            return "handled"
        self.print(f"unknown command {command} — try /attach, /status or /quit")
        return "handled"

    def _attach(self, argument: str) -> None:
        if not argument:
            self.print("/attach needs a path, e.g. /attach ./spec.pdf")
            return
        try:
            attachment = attachment_for(argument)
        except ValueError as exc:
            self.print(f"cannot attach: {exc}")
            return
        self.queued.append(attachment)
        self.print(f"attached {Path(attachment.path).name} — it rides your next message")

    # --- the loop ------------------------------------------------------------

    def turn(self, message: str) -> bool:
        """One exchange. Returns True when the interview is complete."""
        self.brains.attachments = list(self.queued)
        self.brains.turn_number = self.state.turn_count + 1
        try:
            self.state, result = run_turn(
                self.state, message, self.brains.interviewer, self.brains.scribe,
                project=self.project,
                attachments=[a.path for a in self.queued],
            )
        finally:
            self.queued.clear()
            self.brains.attachments = []

        if result.complete:
            self.print("\n" + summary_table(self.state))
            self.print("\n" + HANDOVER)
            return True
        return False

    def run(self, fresh: bool) -> int:
        if fresh:
            self.print(IDEA_PROMPT)
            idea = self.read(PROMPT)
            if self.turn(idea):
                return self._finish()
        else:
            done = completeness(self.state)
            settled = sum(1 for key in CONVERSATIONAL_KEYS if done[key])
            self.print(
                f"resuming at turn {self.state.turn_count}, "
                f"{settled} of {len(CONVERSATIONAL_KEYS)} boxes confirmed"
            )

        while True:
            try:
                line = self.read(PROMPT)
            except (EOFError, KeyboardInterrupt):
                self.print("\n" + RESUME_HINT)
                return self._finish()

            action = self.handle_command(line)
            if action == "quit":
                self.print(RESUME_HINT)
                return self._finish()
            if action == "handled":
                continue

            try:
                if self.turn(line):
                    return self._finish()
            except KeyboardInterrupt:
                self.print("\nturn cancelled. " + RESUME_HINT)
                return self._finish()
            except ScribeParseError as exc:
                self.print(f"\n{exc}")
                return self._finish(1)

    def _finish(self, code: int = 0) -> int:
        if self.brains.receipts:
            self.print(receipt_line(self.brains.receipts))
        return code


def start(slug: str, root: Path | None = None, route: Any = None,
          printer: Any = print, reader: Any = input) -> int:
    """Compose everything and run one interview."""
    import workspace
    from switchboard.registry import load_registry
    from workspace import MeterRouter

    project, created = open_or_create(slug, root, workspace)
    printer(f"=== INTENT: {slug} ({'created' if created else 'existing'}) ===")

    registry = load_registry(_registry_path(project))
    meter = MeterRouter(
        lambda pid: project.meter_path if pid == slug else None,
        default_path=project.meter_path,
    )
    state = load_state(project)
    fresh = state is None
    brains = Brains(slug=slug, registry=registry, meter=meter, route=route,
                    on_delta=_delta_printer(printer), project=project)
    return Session(slug, project, brains, state or new_state(slug),
                   printer, reader).run(fresh)


def _registry_path(project: Any) -> Path:
    """The project's registry if it has one, else the factory's (R-012)."""
    global_registry = Path(__file__).resolve().parents[3] / "switchboard" / "registry.toml"
    return project.effective_registry_path(global_registry)


def _delta_printer(printer: Any):
    def emit(delta: str) -> None:
        printer(delta, end="", flush=True)

    return emit
