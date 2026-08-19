"""Packet: P-014 — Intent, Part Two: The Live Interview.

One job: turn the Switchboard into the two callable shapes P-013's engine asks
for — `interviewer_fn` and `scribe_fn`.

This is the composition edge, and it is the ONLY module allowed to know about
all three packages at once. The engine stays brainless, the Workspace stays a
leaf, the Switchboard never hears the word "interview": wiring, not organs.

Version: 0.1.0
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from intent.state import ScribeUpdate, Turn
from switchboard.request import Attachment, Message, SwitchboardRequest
from switchboard.tags import CallTags

DEPARTMENT = "intent"
INTERVIEWER_ROLE = "interviewer"
SCRIBE_ROLE = "scribe"

# Extension -> attachment kind, mirroring what the Switchboard's adapters accept.
KINDS: dict[str, str] = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".gif": "image", ".pdf": "pdf", ".md": "text", ".txt": "text",
}

INTERVIEWER_SYSTEM = """You are Foundry's Interviewer. You are talking to a founder about \
software they want built, and your only job this turn is to ask ONE good question.

You do not decide whether anything is complete — code does that, and it has already \
told you below what is still missing. Do not list the boxes, do not number them, do \
not explain the process. Ask one question, in plain words, the way a sharp colleague \
would over coffee.

If a contradiction is given to you, raise it first and plainly: name what was said \
earlier, what was said now, state which one you are going with, and ask them to \
confirm.

If confirmations are pending, ask for them directly — "shall I take that as settled?" \
— because nothing counts until they say so."""

SCRIBE_SYSTEM = """You are Foundry's Scribe. You read an interview transcript and \
extract structured content. You output STRICT JSON and nothing else — no prose, no \
commentary, no code fences.

The JSON object has these keys, all optional:
  "boxes": {box_key: {content object}}   content you can now fill or update
  "confirmed_by_user": [box_key]         boxes the user's LAST message explicitly affirmed
  "proposed_by": {box_key: "user"|"interviewer"}  who authored each proposal
  "contradictions": [{"box_key":..., "earlier":..., "later":...}]
  "resolved_contradictions": [box_key]   conflicts the user's last message settled

Rules you must not break:
- Only list a box in confirmed_by_user when the user AFFIRMED it in their own words.
  Enthusiasm about the project is not confirmation of a box.
- If the user deflected ("you decide", "whatever you think"), you may propose content
  and mark proposed_by for that box as "interviewer".
- Never invent content the transcript does not support.

The eight box keys are: goal, users, workflows, data, boundaries, research,
non_negotiables, website."""

RETRY_INSTRUCTION = (
    "Your previous reply was not valid JSON matching the required shape. "
    "Reply again with ONLY the JSON object — no prose, no code fences."
)


class ScribeParseError(RuntimeError):
    """The Scribe would not produce usable JSON. Names the role, keeps the reply."""


def attachment_for(path: str | Path) -> Attachment:
    """Build an Attachment, or say why the file cannot be one."""
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise ValueError(f"no such file: {resolved}")
    kind = KINDS.get(resolved.suffix.lower())
    if kind is None:
        raise ValueError(
            f"{resolved.name}: '{resolved.suffix}' is not an attachable kind "
            f"(known: {', '.join(sorted(set(KINDS)))})"
        )
    return Attachment(kind=kind, path=str(resolved))


def strip_fences(text: str) -> str:
    """Remove a ```json fence if the model wrapped its JSON in one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip()


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
        response = self._route()(
            request, self.registry, None, None, self.meter, on_chunk
        )
        self.receipts.append(response)
        return response

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
        raw = self._call(SCRIBE_ROLE, SCRIBE_SYSTEM, messages, None).content
        parsed = self._parse(raw)
        if parsed is not None:
            return parsed

        retry = messages + [Message(role="user", content=RETRY_INSTRUCTION)]
        second = self._call(SCRIBE_ROLE, SCRIBE_SYSTEM, retry, None).content
        parsed = self._parse(second)
        if parsed is not None:
            return parsed

        self._log_failure(second)
        raise ScribeParseError(
            f"role '{SCRIBE_ROLE}' did not return usable JSON after one retry; "
            f"raw reply preserved in the project build log. Reply was: "
            f"{second[:200]!r}"
        )

    @staticmethod
    def _parse(raw: str) -> ScribeUpdate | None:
        try:
            return ScribeUpdate.model_validate(json.loads(strip_fences(raw)))
        except Exception:
            return None

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
