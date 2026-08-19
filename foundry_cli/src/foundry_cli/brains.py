"""Packet: T-013 — timeouts and progress.

One job: turn the Switchboard into the two callable shapes P-013's engine asks
for — `interviewer_fn` and `scribe_fn`.

This is the composition edge, and it is the ONLY module allowed to know about
all three packages at once. The engine stays brainless, the Workspace stays a
leaf, the Switchboard never hears the word "interview": wiring, not organs.

Version: 0.5.0
"""

from __future__ import annotations

import json
from collections.abc import Callable
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from intent.state import ScribeUpdate, Turn

from foundry_cli.shapes import parse_as, parse_update
from foundry_cli.timeouts import (
    BrainTimeout,
    completion_with_timeout,
    is_timeout,
    timeout_class,
)
from foundry_cli.prompts import (
    INTERVIEWER_SYSTEM,
    RESEARCHER_SYSTEM,
    RETRY_INSTRUCTION,
    scribe_system,
)
from switchboard.request import Attachment, Message, SwitchboardRequest
from switchboard.tags import CallTags

DEPARTMENT = "intent"


INTERVIEWER_ROLE = "interviewer"
SCRIBE_ROLE = "scribe"
RESEARCHER_ROLE = "researcher"























class ScribeParseError(RuntimeError):
    """The Scribe would not produce usable JSON. Names the role, keeps the reply."""






def as_messages(transcript: list[Turn]) -> list[Message]:
    """The transcript as chat messages. The interviewer speaks as assistant."""
    messages = [
        Message(role="assistant" if turn.role == "interviewer" else "user",
                content=turn.content)
        for turn in transcript
    ]
    return messages or [Message(role="user", content="(no transcript yet)")]


@dataclass
class Brains:
    """The two shapes the engine wants, wired to real models.

    `route` is injectable so every test in this package can run offline: the
    fake goes in at the route_call boundary, which is the only place the CLI
    touches the Switchboard.
    """

    slug: str
    registry: Any
    meter: Any = None
    route: Callable[..., Any] | None = None
    on_delta: Callable[[str], None] | None = None
    project: Any = None
    on_waiting: Callable[[str, bool], None] | None = None
    on_ready: Callable[[], None] | None = None
    attachments: list[Attachment] = field(default_factory=list)
    receipts: list[Any] = field(default_factory=list)
    turn_number: int = 0

    def _route(self) -> Callable[..., Any]:
        if self.route is not None:
            return self.route
        from switchboard.router import route_call

        return route_call

    def _tags(self, role: str) -> CallTags:
        return CallTags(
            project_id=self.slug,
            department=DEPARTMENT,
            role=role,
            attempt_number=self.turn_number or None,
        )

    def _call(self, role: str, system: str, messages: list[Message],
              on_chunk: Callable[[str], None] | None) -> Any:
        request = SwitchboardRequest(
            tags=self._tags(role),
            messages=messages,
            system=system,
            attachments=list(self.attachments),
        )
        seconds, retries = timeout_class(role)
        searching = self._searches(role)
        started = time.monotonic()

        for attempt in range(retries + 1):
            self._begin_wait(role, searching)
            try:
                response = self._route()(
                    request, self.registry, completion_with_timeout(seconds),
                    None, self.meter, self._first_delta_clears(on_chunk),
                )
            except Exception as exc:
                self._end_wait()
                if not is_timeout(exc) or attempt == retries:
                    if is_timeout(exc):
                        raise BrainTimeout(self._timeout_message(
                            role, time.monotonic() - started)) from exc
                    raise
                continue
            self._end_wait()
            self.receipts.append(response)
            return response
        raise BrainTimeout(  # pragma: no cover - the loop always returns or raises
            self._timeout_message(role, time.monotonic() - started))

    def _timeout_message(self, role: str, elapsed: float) -> str:
        return (
            f"the '{role}' took longer than {elapsed:.0f}s and was given up on. "
            f"Nothing is lost — the interview is saved after every completed "
            f"turn. Resume with: python -m foundry_cli intent {self.slug}"
        )

    def _searches(self, role: str) -> bool:
        try:
            return bool(self.registry.resolve(role).web_search)
        except Exception:
            return False

    def _begin_wait(self, role: str, searching: bool) -> None:
        if self.on_waiting is not None:
            self.on_waiting(role, searching)

    def _end_wait(self) -> None:
        if self.on_ready is not None:
            self.on_ready()

    def _first_delta_clears(
        self, on_chunk: Callable[[str], None] | None
    ) -> Callable[[str], None] | None:
        """Wrap the delta callback so the progress line vanishes on first output.

        Silence must always mean working (T-013): the line goes up before the
        call and comes down the moment there is something real to show.
        """
        if on_chunk is None:
            return None
        cleared = {"done": False}

        def emit(delta: str) -> None:
            if not cleared["done"]:
                cleared["done"] = True
                self._end_wait()
            on_chunk(delta)

        return emit

    # --- the two shapes the engine asks for ---------------------------------

    def interviewer(
        self, transcript: list[Turn], box_status: dict[str, str],
        directives: dict[str, Any],
    ) -> str:
        """Stream the next question, and return what the Switchboard assembled.

        The returned content is route_call's, never a locally re-joined delta
        buffer: deltas are for the human's eyes, the response is the record.
        One source of truth — the R-018 lesson.
        """
        system = (
            f"{INTERVIEWER_SYSTEM}\n\nSTATE (from code, not opinion):\n"
            f"{json.dumps({'box_status': box_status, **directives}, indent=2)}"
        )
        response = self._call(
            INTERVIEWER_ROLE, system, as_messages(transcript), self.on_delta
        )
        return response.content

    def scribe(
        self, transcript: list[Turn], current_boxes: dict[str, Any]
    ) -> ScribeUpdate:
        """Extract structured content, with exactly one corrective retry."""
        messages = as_messages(transcript) + [
            Message(
                role="user",
                content=(
                    "Current boxes:\n"
                    f"{json.dumps(current_boxes, indent=2, default=str)}\n\n"
                    "Extract from the LAST user message. JSON only."
                ),
            )
        ]
        system = scribe_system()
        raw = self._call(SCRIBE_ROLE, system, messages, None).content
        parsed, problem = parse_update(raw)
        if parsed is not None:
            return parsed

        # The correction NAMES what was wrong. A generic "that was not JSON"
        # cannot fix a reply that was valid JSON in the wrong shape (T-012).
        retry = messages + [Message(
            role="user", content=f"{RETRY_INSTRUCTION} {problem}".strip())]
        second = self._call(SCRIBE_ROLE, system, retry, None).content
        parsed, problem = parse_update(second)
        if parsed is not None:
            return parsed

        self._log_failure(second)
        raise ScribeParseError(
            f"role '{SCRIBE_ROLE}' did not return usable content after one "
            f"retry ({problem}); raw reply preserved in the project build log. "
            f"Reply was: {second[:200]!r}"
        )

    def researcher(self, brief: dict[str, Any]) -> Any:
        """Sweep the market for this intent, with the same JSON discipline.

        The role's registry entry decides whether it searches and how hard —
        route_call auto-attaches the spec (P-016). Nothing here asks for search,
        which is why turning it on is a config change and not a code change.
        """
        from intent.research import ResearchFindings

        messages = [Message(role="user", content=(
            "Here is the founder's stated intent. Research the market and "
            "return the JSON described in your instructions.\n\n"
            f"{json.dumps(brief, indent=2, default=str)}"
        ))]
        raw = self._call(RESEARCHER_ROLE, RESEARCHER_SYSTEM, messages, None).content
        parsed = parse_as(raw, ResearchFindings)
        if parsed is not None:
            return parsed

        retry = messages + [Message(role="user", content=RETRY_INSTRUCTION)]
        second = self._call(
            RESEARCHER_ROLE, RESEARCHER_SYSTEM, retry, None
        ).content
        parsed = parse_as(second, ResearchFindings)
        if parsed is not None:
            return parsed

        self._log_failure(second)
        raise ScribeParseError(
            f"role '{RESEARCHER_ROLE}' did not return usable JSON after one "
            f"retry; raw reply preserved in the project build log. Reply was: "
            f"{second[:200]!r}"
        )

    def _log_failure(self, raw: str) -> None:
        """A lost extraction is a lost user answer — never swallowed silently."""
        if self.project is None:
            return
        path = Path(self.project.build_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n- Scribe returned unusable JSON twice (turn "
                f"{self.turn_number}). Raw reply:\n\n```\n{raw}\n```\n"
            )
