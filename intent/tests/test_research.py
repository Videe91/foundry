"""Packet: P-016 — Research Both Ways: the sweep.

One job: test run_research — that it refuses an unfinished interview, briefs the
researcher on conversational boxes only, enforces the challenge discipline,
dates its findings, archives before overwriting, and fills box 6.

The researcher is a fake. That is the design: the sweep must be correct with a
mediocre model on the other end.

Version: 0.1.0
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from intent import new_state, save_state
from intent.research import (
    ARCHIVE_FILENAME,
    FINDINGS_TTL,
    Challenge,
    Player,
    ResearchError,
    ResearchFindings,
    archive_path,
    build_brief,
    findings_path,
    incomplete_boxes,
    render_report,
    report_path,
    run_research,
)
from intent.skeleton import CONFIRMED, CONVERSATIONAL_KEYS, RESEARCH_KEY
from intent.state import utc_now
from workspace import create_project

FULL: dict[str, dict[str, Any]] = {
    "goal": {"summary": "a tool", "victory_conditions": ["ships", "is used"]},
    "users": {"users": [{"name": "founder", "needs": "speed"}]},
    "workflows": {"workflows": [{"story": "uploads", "mode": "automate"}]},
    "data": {"entities": ["invoice"], "sensitive": []},
    "boundaries": {"exclusions": ["no payments"]},
    "non_negotiables": {"security_level": "standard", "scale": "small",
                        "budget": "$100/mo"},
    "website": {"needed": False},
}


def _findings(**kwargs: Any) -> ResearchFindings:
    kwargs.setdefault("challenges", [Challenge(
        claim="TrustedForm already does provenance in the US",
        against="goal", sources=["https://example.com/trustedform"])])
    kwargs.setdefault("players", [Player(name="Rival", url="https://rival.example",
                                         what_they_do="the same thing",
                                         relevance="direct competitor")])
    kwargs.setdefault("sources", ["https://example.com/market"])
    return ResearchFindings(**kwargs)


def _project(tmp_path: Path, complete: bool = True):
    project = create_project("demo-app", "Demo App", root=tmp_path)
    state = new_state("demo-app")
    keys = list(FULL) if complete else ["goal", "users"]
    for key in keys:
        state.boxes[key].content = FULL[key]
        state.boxes[key].status = CONFIRMED
        state.boxes[key].proposed_by = "user"
    save_state(project, state)
    return project


def _researcher(findings: ResearchFindings | None = None):
    seen: dict[str, Any] = {}

    def fn(brief: dict[str, Any]) -> ResearchFindings:
        seen["brief"] = brief
        return findings or _findings()

    fn.seen = seen  # type: ignore[attr-defined]
    return fn


# --- it refuses an unfinished interview ------------------------------------


def test_an_incomplete_interview_is_refused_naming_what_is_open(
    tmp_path: Path,
) -> None:
    """Research against a half-stated intent challenges something the founder
    has not finished saying."""
    project = _project(tmp_path, complete=False)
    with pytest.raises(ResearchError) as excinfo:
        run_research(project, _researcher())
    message = str(excinfo.value)
    assert "not complete" in message
    for key in ("workflows", "data", "boundaries", "website"):
        assert key in message


def test_a_project_with_no_interview_at_all_is_refused(tmp_path: Path) -> None:
    project = create_project("demo-app", "Demo App", root=tmp_path)
    with pytest.raises(ResearchError, match="no interview"):
        run_research(project, _researcher())


def test_incomplete_boxes_never_lists_the_internal_one() -> None:
    """The reserved slot is not the founder's to complete (T-009)."""
    assert RESEARCH_KEY not in incomplete_boxes(new_state("demo"))


# --- the brief: conversational boxes only ----------------------------------


def test_the_brief_excludes_the_internal_box(tmp_path: Path) -> None:
    """A researcher shown box 6 would research our own bookkeeping."""
    project = _project(tmp_path)
    fn = _researcher()
    run_research(project, fn)
    brief = fn.seen["brief"]
    assert RESEARCH_KEY not in brief
    assert set(brief) == set(CONVERSATIONAL_KEYS)
    assert "research" not in json.dumps(brief).lower()


def test_the_brief_carries_only_confirmed_content(tmp_path: Path) -> None:
    """Proposed content is not the intent — it is not consent (R-033b)."""
    project = _project(tmp_path)
    state = __import__("intent").load_state(project)
    state.boxes["website"].status = "proposed"
    save_state(project, state)

    fn = _researcher()
    with pytest.raises(ResearchError):
        run_research(project, fn)  # demoting a box makes it incomplete


# --- the challenge discipline (contract 5) ---------------------------------


def test_no_challenges_and_no_reason_is_rejected() -> None:
    """Silence is not allowed: the market agreeing with everything is a claim."""
    with pytest.raises(Exception) as excinfo:
        ResearchFindings(players=[], challenges=[])
    assert "no_challenges_because" in str(excinfo.value)


def test_no_challenges_with_a_stated_reason_is_accepted() -> None:
    findings = ResearchFindings(
        challenges=[], no_challenges_because="nobody serves this market yet")
    assert findings.open_challenges == 0


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_a_blank_reason_does_not_count_as_a_reason(blank: str) -> None:
    """Discriminating: whitespace would satisfy a naive presence check."""
    with pytest.raises(Exception):
        ResearchFindings(challenges=[], no_challenges_because=blank)


def test_a_challenge_names_what_it_presses_on() -> None:
    """P-017 shows the challenge beside the thing being signed."""
    challenge = Challenge(claim="regulated activity", against="boundaries")
    assert challenge.against == "boundaries"
    assert challenge.acknowledged is False


def test_open_challenges_counts_only_unacknowledged() -> None:
    findings = _findings(challenges=[
        Challenge(claim="a", against="goal"),
        Challenge(claim="b", against="users", acknowledged=True),
    ])
    assert findings.open_challenges == 1


# --- dates (contract 6) -----------------------------------------------------


def test_findings_expire_thirty_days_after_generation() -> None:
    findings = _findings()
    assert findings.expires_at - findings.generated_at == FINDINGS_TTL
    assert FINDINGS_TTL == timedelta(days=30)


def test_expiry_is_computed_not_asserted() -> None:
    old = _findings(generated_at=utc_now() - timedelta(days=31))
    assert old.expired() is True
    assert _findings().expired() is False


def test_the_report_prints_both_dates_prominently() -> None:
    findings = _findings()
    report = render_report(findings, "demo-app")
    assert findings.generated_at.isoformat() in report
    assert findings.expires_at.isoformat() in report
    assert report.index("Generated") < report.index("Who is already doing this")


def test_the_report_shows_challenges_with_what_they_press_on() -> None:
    report = render_report(_findings(), "demo-app")
    assert "presses on: goal" in report
    assert "TrustedForm" in report


def test_a_report_with_no_challenges_prints_the_stated_reason() -> None:
    report = render_report(
        ResearchFindings(challenges=[], no_challenges_because="market is empty"),
        "demo-app")
    assert "market is empty" in report


# --- the happy path ---------------------------------------------------------


def test_findings_are_written_and_box_six_is_filled(tmp_path: Path) -> None:
    project = _project(tmp_path)
    findings = run_research(project, _researcher())

    assert findings_path(project).is_file()
    assert report_path(project).is_file()
    assert not list(Path(project.intent_dir).glob("*.tmp"))

    state = __import__("intent").load_state(project)
    box = state.boxes[RESEARCH_KEY]
    assert box.content["status"] == "completed"
    assert box.content["challenges_open"] == 1
    assert box.content["expires_at"] == findings.expires_at.isoformat()


def test_only_the_sweep_writes_box_six(tmp_path: Path) -> None:
    """R-036: mid-interview search informs questions, never fills boxes."""
    project = _project(tmp_path)
    before = __import__("intent").load_state(project).boxes[RESEARCH_KEY].content
    assert before == {"status": "reserved"}

    run_research(project, _researcher())
    after = __import__("intent").load_state(project).boxes[RESEARCH_KEY].content
    assert after["status"] == "completed"


def test_the_findings_json_round_trips(tmp_path: Path) -> None:
    project = _project(tmp_path)
    run_research(project, _researcher())
    restored = ResearchFindings.model_validate_json(
        findings_path(project).read_text(encoding="utf-8"))
    assert restored.challenges[0].against == "goal"
    assert restored.players[0].name == "Rival"


# --- re-running (contract 7) ------------------------------------------------


def test_a_second_sweep_archives_the_first_before_overwriting(
    tmp_path: Path,
) -> None:
    """Findings are replaced, never silently lost — a sweep that contradicts
    last month's sweep is itself a finding."""
    project = _project(tmp_path)
    run_research(project, _researcher(_findings(
        challenges=[Challenge(claim="first sweep", against="goal")])))
    run_research(project, _researcher(_findings(
        challenges=[Challenge(claim="second sweep", against="users")])))

    archive = archive_path(project).read_text(encoding="utf-8")
    current = report_path(project).read_text(encoding="utf-8")
    assert "first sweep" in archive
    assert "second sweep" in current
    assert "first sweep" not in current


def test_the_first_sweep_archives_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    run_research(project, _researcher())
    assert not (Path(project.intent_dir) / ARCHIVE_FILENAME).exists()


def test_a_re_run_resets_the_box_six_counts(tmp_path: Path) -> None:
    project = _project(tmp_path)
    run_research(project, _researcher(_findings(challenges=[
        Challenge(claim="a", against="goal"), Challenge(claim="b", against="users")
    ])))
    assert __import__("intent").load_state(project).boxes[
        RESEARCH_KEY].content["challenges_open"] == 2

    run_research(project, _researcher(_findings(
        challenges=[], no_challenges_because="resolved since")))
    assert __import__("intent").load_state(project).boxes[
        RESEARCH_KEY].content["challenges_open"] == 0
