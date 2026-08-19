"""Packet: P-016 — Research Both Ways: the sweep.

One job: on a COMPLETED interview, find the real market, record what it says,
and — the part that matters — record where the market DISAGREES with the intent.

Design doc §15.1's rulebook, step 4: gather, attach sources, synthesize, then
**challenge the intent**. Research that only confirms is flattery with citations.

R-036: this is the only thing that writes box 6. Mid-interview search informs
QUESTIONS; it never fills boxes. Only the user and this sweep write the
constitution.

The brain arrives as an injected callable, by shape. This module imports neither
switchboard nor litellm, and the subprocess guards enforce it.

Version: 0.1.0
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from intent.rules import completeness
from intent.skeleton import CONFIRMED, CONVERSATIONAL_KEYS, RESEARCH_KEY
from intent.state import InterviewState, utc_now
from intent.store import load_state, save_state

# Findings go stale. Thirty days is the rulebook's dated-findings law made
# concrete: long enough that a sweep is not busywork, short enough that a
# competitor launched last month is not missing from a constitution signed
# today. P-017 refuses to sign on expired findings.
FINDINGS_TTL = timedelta(days=30)

FINDINGS_FILENAME = "research.json"
REPORT_FILENAME = "research.md"
ARCHIVE_FILENAME = "research-archive.md"


class ResearchError(Exception):
    """The sweep cannot proceed, or its findings cannot be trusted."""


class Player(BaseModel):
    """Someone already in this market."""

    name: str
    url: str = ""
    what_they_do: str = ""
    relevance: str = ""


class Challenge(BaseModel):
    """Something the market says that the intent does not account for.

    `against` names the part of the intent it presses on, so P-017 can show the
    challenge beside the very thing the founder is about to sign.
    """

    claim: str
    against: str
    sources: list[str] = Field(default_factory=list)
    acknowledged: bool = False


class ResearchFindings(BaseModel):
    """One sweep's output, dated and expiring."""

    players: list[Player] = Field(default_factory=list)
    table_stakes: list[str] = Field(default_factory=list)
    edge: list[str] = Field(default_factory=list)
    challenges: list[Challenge] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    no_challenges_because: str = ""
    generated_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _dated_and_challenged(self) -> "ResearchFindings":
        """Silence is not allowed (contract 5).

        A sweep that raises no challenge must SAY that the market agrees, in
        words, so the claim can be doubted. An empty list with no reason is
        indistinguishable from a researcher that did not look.
        """
        if self.expires_at is None:
            self.expires_at = self.generated_at + FINDINGS_TTL
        if not self.challenges and not self.no_challenges_because.strip():
            raise ValueError(
                "findings must carry at least one challenge, or state "
                "'no_challenges_because' — the market agreeing with everything "
                "is a claim, and it has to be made out loud to be doubted"
            )
        return self

    @property
    def open_challenges(self) -> int:
        return sum(1 for c in self.challenges if not c.acknowledged)

    def expired(self, now: datetime | None = None) -> bool:
        return (now or utc_now()) > (self.expires_at or self.generated_at)


def incomplete_boxes(state: InterviewState) -> list[str]:
    """Conversational boxes not yet settled, in skeleton order."""
    done = completeness(state)
    return [key for key in CONVERSATIONAL_KEYS if not done[key]]


def build_brief(state: InterviewState) -> dict[str, Any]:
    """What the researcher is told about the intent.

    CONVERSATIONAL boxes only — the internal slot is ours, and a researcher
    shown it would research our own bookkeeping (T-009).
    """
    return {
        key: state.boxes[key].content
        for key in CONVERSATIONAL_KEYS
        if state.boxes[key].status == CONFIRMED
    }


def findings_path(project: Any) -> Path:
    return Path(project.intent_dir) / FINDINGS_FILENAME


def report_path(project: Any) -> Path:
    return Path(project.intent_dir) / REPORT_FILENAME


def archive_path(project: Any) -> Path:
    return Path(project.intent_dir) / ARCHIVE_FILENAME


def render_report(findings: ResearchFindings, slug: str) -> str:
    """The human-readable sweep. Dates first — a finding without a date is a
    rumour, and one past its date is a rumour that used to be true."""
    lines = [
        f"# Research — {slug}", "",
        f"**Generated:** {findings.generated_at.isoformat()}",
        f"**Expires:** {findings.expires_at.isoformat()}  "
        "(P-017 refuses to sign on expired findings)", "",
        "## Who is already doing this", "",
    ]
    if findings.players:
        lines += ["| player | what they do | why it matters |", "|---|---|---|"]
        for player in findings.players:
            name = f"[{player.name}]({player.url})" if player.url else player.name
            lines.append(
                f"| {name} | {player.what_they_do} | {player.relevance} |"
            )
    else:
        lines.append("_No players found — which is itself worth doubting._")

    lines += ["", "## Table stakes", ""]
    lines += [f"- {item}" for item in findings.table_stakes] or ["_none recorded_"]
    lines += ["", "## Where an edge could be", ""]
    lines += [f"- {item}" for item in findings.edge] or ["_none recorded_"]

    lines += ["", "## Challenges to the intent", ""]
    if findings.challenges:
        for challenge in findings.challenges:
            lines.append(f"- **{challenge.claim}**")
            lines.append(f"  - presses on: {challenge.against}")
            if challenge.sources:
                lines.append(f"  - sources: {', '.join(challenge.sources)}")
    else:
        lines.append(
            f"_No challenges raised. Stated reason: "
            f"{findings.no_challenges_because}_"
        )

    lines += ["", "## Sources", ""]
    lines += [f"- {source}" for source in findings.sources] or ["_none recorded_"]
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def archive_previous(project: Any) -> bool:
    """Move an existing report into the archive before it is overwritten.

    Findings are replaced, never silently lost: a sweep that contradicts last
    month's sweep is itself a finding (contract 7).
    """
    report = report_path(project)
    if not report.is_file():
        return False
    with archive_path(project).open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n---\n\n## Archived {utc_now().isoformat()}\n\n")
        handle.write(report.read_text(encoding="utf-8"))
    return True


def run_research(
    project: Any,
    researcher_fn: Callable[[dict[str, Any]], ResearchFindings],
) -> ResearchFindings:
    """Sweep the market for a completed interview (contract 4).

    Refuses an unfinished interview: research against a half-stated intent
    produces challenges to something the founder has not finished saying.
    """
    state = load_state(project)
    if state is None:
        raise ResearchError(
            f"no interview to research for "
            f"'{getattr(project, 'slug', project)}' — run the interview first"
        )

    missing = incomplete_boxes(state)
    if missing:
        raise ResearchError(
            "the interview is not complete, so there is nothing settled to "
            f"research against. Still open: {', '.join(missing)}"
        )

    findings = researcher_fn(build_brief(state))

    archive_previous(project)
    _atomic_write(findings_path(project), findings.model_dump_json(indent=2))
    _atomic_write(
        report_path(project),
        render_report(findings, str(getattr(project, "slug", ""))),
    )

    # Box 6, filled by the sweep and by nothing else (R-036). Still internal:
    # its content never reaches a model, and no founder is asked about it.
    state.boxes[RESEARCH_KEY].content = {
        "status": "completed",
        "generated_at": findings.generated_at.isoformat(),
        "expires_at": findings.expires_at.isoformat(),
        "challenges_open": findings.open_challenges,
    }
    save_state(project, state)
    return findings
