"""Packet: P-016 — Research Both Ways: the CLI side.

One job: test `foundry research <slug>`, the researcher's JSON discipline, and
the two laws the packet singles out — the engine stays deaf to search (R-036),
and the Scribe never searches.

Version: 0.1.0
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FULL_BOXES, SLUG, FakeRoute, Printer, Reader, fake_registry

from foundry_cli.brains import RESEARCHER_ROLE, Brains, ScribeParseError
from foundry_cli.research_cmd import ACKNOWLEDGED_AT_SIGNING, render_summary, start
from intent import load_state, new_state, run_turn, save_state
from intent.research import Challenge, ResearchFindings, findings_path, report_path
from intent.skeleton import CONFIRMED, RESEARCH_KEY
from switchboard.registry import ModelRegistry, RoleRoute
from workspace import create_project

FINDINGS_JSON = json.dumps({
    "players": [{"name": "Rival", "url": "https://rival.example",
                 "what_they_do": "the same thing", "relevance": "direct"}],
    "table_stakes": ["consent capture"],
    "edge": ["UK-specific compliance"],
    "challenges": [{"claim": "TrustedForm already does this in the US",
                    "against": "goal", "sources": ["https://example.com"]}],
    "sources": ["https://example.com"],
})


def _completed_project(tmp_path: Path):
    project = create_project(SLUG, "Demo App", root=tmp_path)
    state = new_state(SLUG)
    for key, content in FULL_BOXES.items():
        state.boxes[key].content = content
        state.boxes[key].status = CONFIRMED
        state.boxes[key].proposed_by = "user"
    save_state(project, state)
    return project


def _searching_registry() -> ModelRegistry:
    """interviewer searches, scribe does not — the shipped shape."""
    return ModelRegistry(roles={
        "interviewer": RoleRoute(model="anthropic/claude-sonnet-5", fallbacks=[],
                                 max_tokens=64000, web_search=True,
                                 web_search_max_uses=2),
        "scribe": RoleRoute(model="anthropic/claude-haiku-4-5-20251001",
                            fallbacks=[], max_tokens=64000),
        "researcher": RoleRoute(model="anthropic/claude-sonnet-5", fallbacks=[],
                                max_tokens=64000, web_search=True,
                                web_search_max_uses=8),
    })


# --- the Scribe never searches (contract 3) --------------------------------


def test_the_scribe_carries_no_tools_even_when_the_interviewer_does() -> None:
    """A Scribe that could look things up could write the market's opinion into
    a box the founder never confirmed.

    Routed through the REAL route_call so auto-attach makes the decision — a
    fake router would only prove what the fake was told to do.
    """
    from types import SimpleNamespace

    from switchboard.router import route_call

    sent: list[dict[str, Any]] = []

    usage = SimpleNamespace(
        prompt_tokens=10, completion_tokens=2, total_tokens=12,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0))

    def completion(**kwargs: Any) -> Any:
        sent.append(kwargs)
        if not kwargs.get("stream"):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content='{"boxes":{}}'))],
                usage=usage)

        def emit() -> Any:
            yield SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content='{"boxes":{}}'))])
            yield SimpleNamespace(choices=[], usage=usage)

        return emit()

    def spy(request, registry, _completion_fn, cost_fn, meter, on_chunk=None):
        return route_call(request, registry, completion, cost_fn, meter, on_chunk)

    from intent.state import Turn

    brains = Brains(slug=SLUG, registry=_searching_registry(), route=spy)
    transcript = [Turn(role="user", content="something like TrustedForm")]

    brains.scribe(transcript, {})
    assert "tools" not in sent[-1], "the scribe was handed a search tool"

    brains.interviewer(transcript, {}, {"ask_one_question": True})
    assert "tools" in sent[-1], "the interviewer lost its search tool"
    assert sent[-1]["tools"][0]["max_uses"] == 2, "the role's own ceiling"


# --- the engine stays deaf to search (R-036) -------------------------------


def test_run_turn_produces_identical_state_whether_the_model_searched() -> None:
    """Search happens INSIDE the model's turn. The engine cannot tell, and a
    change in engine behaviour would mean the seam had leaked."""
    reply = "and who is it for?"

    def searched(*_a: Any) -> str:
        return reply

    def unsearched(*_a: Any) -> str:
        return reply

    from intent.state import ScribeUpdate

    def scribe(*_a: Any) -> ScribeUpdate:
        return ScribeUpdate()

    first, first_result = run_turn(new_state(SLUG), "hi", searched, scribe)
    second, second_result = run_turn(new_state(SLUG), "hi", unsearched, scribe)

    left = first.model_dump()
    right = second.model_dump()
    for state in (left, right):
        for turn in state["transcript"]:
            turn["at"] = None
    assert left == right
    assert first_result.model_dump() == second_result.model_dump()


def test_the_engine_source_never_mentions_search() -> None:
    """R-036, asserted structurally: no engine change was needed or made."""
    import inspect

    import intent.engine as engine

    source = inspect.getsource(engine).lower()
    # Not a bare "search": the engine legitimately discusses the RESEARCH box,
    # and "research" contains "search". What must be absent is any awareness of
    # the capability itself.
    for token in ("web_search", "search_tool", "websearchspec", "tools"):
        assert token not in source, f"the engine knows about {token}"


# --- the researcher's JSON discipline --------------------------------------


def test_valid_findings_json_becomes_findings() -> None:
    route = FakeRoute(replies=[FINDINGS_JSON])
    brains = Brains(slug=SLUG, registry=fake_registry(), route=route)
    findings = brains.researcher({"goal": FULL_BOXES["goal"]})
    assert isinstance(findings, ResearchFindings)
    assert findings.challenges[0].against == "goal"
    assert route.calls[0]["role"] == RESEARCHER_ROLE


def test_a_malformed_reply_gets_one_retry_then_fails_loudly(tmp_path: Path) -> None:
    project = create_project(SLUG, "Demo", root=tmp_path)
    route = FakeRoute(replies=["I found some competitors!", "still prose"])
    brains = Brains(slug=SLUG, registry=fake_registry(), route=route,
                    project=project)
    with pytest.raises(ScribeParseError) as excinfo:
        brains.researcher({})
    assert RESEARCHER_ROLE in str(excinfo.value)
    assert len(route.calls) == 2
    assert "still prose" in Path(project.build_log_path).read_text(encoding="utf-8")


def test_findings_that_break_the_challenge_discipline_are_refused() -> None:
    """The model cannot opt out of being challenged by returning an empty list."""
    route = FakeRoute(replies=[json.dumps({"players": [], "challenges": []}),
                               json.dumps({"players": [], "challenges": []})])
    brains = Brains(slug=SLUG, registry=fake_registry(), route=route)
    with pytest.raises(ScribeParseError):
        brains.researcher({})


# --- the command ------------------------------------------------------------


def test_a_completed_project_produces_files_and_a_summary(tmp_path: Path) -> None:
    _completed_project(tmp_path)
    printer = Printer()
    assert start(SLUG, root=tmp_path, route=FakeRoute(replies=[FINDINGS_JSON]),
                 printer=printer) == 0

    out = printer.text
    assert "TrustedForm already does this in the US" in out
    assert "presses on: goal" in out
    assert ACKNOWLEDGED_AT_SIGNING in out
    assert "research.json" in out and "research.md" in out

    from workspace import open_project

    project = open_project(SLUG, root=tmp_path)
    assert findings_path(project).is_file()
    assert report_path(project).is_file()
    assert load_state(project).boxes[RESEARCH_KEY].content["status"] == "completed"


def test_an_incomplete_interview_refuses_and_exits_non_zero(
    tmp_path: Path,
) -> None:
    project = create_project(SLUG, "Demo", root=tmp_path)
    save_state(project, new_state(SLUG))
    printer = Printer()
    assert start(SLUG, root=tmp_path, route=FakeRoute(replies=[FINDINGS_JSON]),
                 printer=printer) == 1
    assert "not complete" in printer.text


def test_the_receipt_line_is_printed(tmp_path: Path) -> None:
    _completed_project(tmp_path)
    printer = Printer()
    start(SLUG, root=tmp_path, route=FakeRoute(replies=[FINDINGS_JSON]),
          printer=printer)
    assert "1 calls" in printer.text and "tokens" in printer.text


def test_the_summary_says_when_there_are_no_challenges() -> None:
    findings = ResearchFindings(challenges=[],
                                no_challenges_because="the market is empty")
    summary = render_summary(findings, {"json": Path("a"), "md": Path("b")})
    assert "0 challenges" in summary
    assert "the market is empty" in summary
