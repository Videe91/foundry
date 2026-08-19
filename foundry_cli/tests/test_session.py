"""Packet: P-014 — Intent, Part Two: The Live Interview.

One job: test the interview loop — fresh start versus resume, the in-conversation
commands, attachments reaching the next turn, receipts, and the honest handover
at completion.

Version: 0.1.0
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from conftest import (
    FULL_BOXES,
    SLUG,
    FakeRoute,
    Printer,
    Reader,
    fake_registry,
    scribe_json,
)

from foundry_cli.session import (
    HANDOVER,
    IDEA_PROMPT,
    RESUME_HINT,
    Session,
    receipt_line,
    start,
    status_table,
    summary_table,
)
from foundry_cli.brains import Brains
from intent import load_state, new_state, save_state


def _session(route: FakeRoute, project, reader: Reader, printer: Printer,
             state=None) -> Session:
    brains = Brains(slug=SLUG, registry=fake_registry(), route=route,
                    project=project, on_delta=lambda d: printer(d, end=""))
    return Session(SLUG, project, brains, state or new_state(SLUG),
                   printer, reader)


def _complete_scribe() -> str:
    return scribe_json(boxes=FULL_BOXES, confirmed_by_user=list(FULL_BOXES))


# --- fresh start vs resume --------------------------------------------------


def test_a_fresh_interview_prompts_for_the_idea_first(project) -> None:
    reader = Reader(["a tool for invoices"])
    printer = Printer()
    route = FakeRoute(replies=[scribe_json(), "and who is it for?"])
    _session(route, project, reader, printer).run(fresh=True)

    assert IDEA_PROMPT in printer.text
    assert route.calls[0]["messages"][0] == "a tool for invoices"


def test_a_resumed_interview_recaps_and_skips_the_idea_prompt(project) -> None:
    state = new_state(SLUG)
    state.turn_count = 4
    state.boxes["goal"].content = FULL_BOXES["goal"]
    state.boxes["goal"].status = "confirmed"
    save_state(project, state)

    printer = Printer()
    _session(FakeRoute(), project, Reader([]), printer, state).run(fresh=False)

    assert "resuming at turn 4" in printer.text
    # 1 of 7, not 2 of 8: the reserved slot is neither the founder's to answer
    # nor theirs to be credited with (T-009).
    assert "1 of 7 boxes confirmed" in printer.text
    assert IDEA_PROMPT not in printer.text


def test_start_resumes_from_disk(project, tmp_path: Path) -> None:
    state = new_state(SLUG)
    state.turn_count = 9
    save_state(project, state)

    printer = Printer()
    start(SLUG, root=tmp_path, route=FakeRoute(), printer=printer,
          reader=Reader([]))
    assert "resuming at turn 9" in printer.text
    assert "(existing)" in printer.text


def test_start_creates_the_project_when_absent(tmp_path: Path) -> None:
    printer = Printer()
    start("brand-new", root=tmp_path, route=FakeRoute(replies=[scribe_json(), "q"]),
          printer=printer, reader=Reader(["an idea"]))
    assert "(created)" in printer.text
    assert (tmp_path / "brand-new" / "project.toml").is_file()


# --- commands ---------------------------------------------------------------


def test_status_prints_the_table_without_spending_a_call(project) -> None:
    route = FakeRoute()
    session = _session(route, project, Reader([]), Printer())
    assert session.handle_command("/status") == "handled"
    assert "boxes complete" in session.print.text
    assert route.calls == []


def test_quit_saves_and_exits_zero(project) -> None:
    printer = Printer()
    reader = Reader(["a tool", "/quit"])
    route = FakeRoute(replies=[scribe_json(), "q"])
    code = _session(route, project, reader, printer).run(fresh=True)

    assert code == 0
    assert RESUME_HINT in printer.text
    assert load_state(project).turn_count == 1, "the turn was saved before quitting"


def test_an_unknown_command_is_named_not_sent_to_a_model(project) -> None:
    route = FakeRoute()
    session = _session(route, project, Reader([]), Printer())
    assert session.handle_command("/wat") == "handled"
    assert "unknown command /wat" in session.print.text
    assert route.calls == []


def test_a_plain_message_is_not_a_command(project) -> None:
    session = _session(FakeRoute(), project, Reader([]), Printer())
    assert session.handle_command("I want a tool") == "not-a-command"


# --- attachments ------------------------------------------------------------


def test_attach_rejects_a_bad_path_at_the_command(project) -> None:
    session = _session(FakeRoute(), project, Reader([]), Printer())
    session.handle_command("/attach ./nope.png")
    assert "cannot attach" in session.print.text
    assert session.queued == []


def test_attach_rejects_an_unknown_extension(project, tmp_path: Path) -> None:
    odd = tmp_path / "notes.rtf"
    odd.write_text("x", encoding="utf-8")
    session = _session(FakeRoute(), project, Reader([]), Printer())
    session.handle_command(f"/attach {odd}")
    assert "cannot attach" in session.print.text
    assert session.queued == []


def test_attach_with_no_path_says_so(project) -> None:
    session = _session(FakeRoute(), project, Reader([]), Printer())
    session.handle_command("/attach")
    assert "needs a path" in session.print.text


def test_a_queued_attachment_reaches_the_next_turn_then_clears(
    project, tmp_path: Path
) -> None:
    doc = tmp_path / "spec.pdf"
    doc.write_bytes(b"%PDF-1.4")
    route = FakeRoute(replies=[scribe_json(), "q", scribe_json(), "q2"])
    session = _session(route, project, Reader([]), Printer())

    session.handle_command(f"/attach {doc}")
    assert len(session.queued) == 1
    session.turn("here is the spec")

    assert all(len(c["attachments"]) == 1 for c in route.calls[:2])
    assert session.queued == [], "the attachment was not cleared after the turn"

    session.turn("and now this")
    assert all(c["attachments"] == [] for c in route.calls[2:])


def test_the_attachment_path_is_recorded_on_the_turn(project, tmp_path: Path) -> None:
    doc = tmp_path / "spec.pdf"
    doc.write_bytes(b"%PDF-1.4")
    session = _session(FakeRoute(replies=[scribe_json(), "q"]), project,
                       Reader([]), Printer())
    session.handle_command(f"/attach {doc}")
    session.turn("see attached")
    assert session.state.transcript[0].attachments == [str(doc)]


# --- receipts ---------------------------------------------------------------


def test_the_receipt_line_totals_known_costs() -> None:
    receipts = [
        SimpleNamespace(usage=SimpleNamespace(total_tokens=100, cost_usd=0.01)),
        SimpleNamespace(usage=SimpleNamespace(total_tokens=50, cost_usd=0.02)),
    ]
    line = receipt_line(receipts)
    assert "2 calls" in line and "150 tokens" in line and "$0.0300" in line


def test_an_unpriced_receipt_makes_the_total_a_floor() -> None:
    """The matrix rule applied to a session: a total containing an unknown
    line item is not a total."""
    receipts = [
        SimpleNamespace(usage=SimpleNamespace(total_tokens=100, cost_usd=0.01)),
        SimpleNamespace(usage=SimpleNamespace(total_tokens=50, cost_usd=None)),
    ]
    line = receipt_line(receipts)
    assert "at least $0.0100" in line
    assert "1 unpriced calls" in line


def test_the_session_prints_its_receipt_on_exit(project) -> None:
    printer = Printer()
    route = FakeRoute(replies=[scribe_json(), "q"])
    _session(route, project, Reader(["a tool", "/quit"]), printer).run(fresh=True)
    assert "2 calls" in printer.text


def test_receipts_are_metered_into_the_projects_ledger(tmp_path: Path) -> None:
    printer = Printer()
    start(SLUG, root=tmp_path, route=FakeRoute(replies=[scribe_json(), "q"]),
          printer=printer, reader=Reader(["a tool", "/quit"]))
    meter = tmp_path / SLUG / "ledger" / "meter.jsonl"
    lines = [json.loads(l) for l in meter.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    assert all(r["tags"]["project_id"] == SLUG for r in lines)
    assert {r["tags"]["role"] for r in lines} == {"scribe", "interviewer"}


# --- completion -------------------------------------------------------------


def test_completion_prints_the_boxes_and_hands_over_honestly(project) -> None:
    printer = Printer()
    route = FakeRoute(replies=[_complete_scribe()])
    session = _session(route, project, Reader([]), printer)

    assert session.turn("everything at once") is True
    assert HANDOVER in printer.text
    assert "P-015" in printer.text
    for key in FULL_BOXES:
        assert key in printer.text


def test_nothing_is_signed_or_advanced(project) -> None:
    """P-015's job. The project must still be a draft afterwards."""
    session = _session(FakeRoute(replies=[_complete_scribe()]), project,
                       Reader([]), Printer())
    session.turn("everything")
    from workspace import open_project

    assert open_project(project.root_dir).status == "draft"
    assert open_project(project.root_dir).signatures == []


def test_the_summary_names_who_settled_each_box(project) -> None:
    session = _session(FakeRoute(replies=[_complete_scribe()]), project,
                       Reader([]), Printer())
    session.turn("everything")
    table = summary_table(session.state)
    assert "[user]" in table
    assert "goal" in table and "website" in table


def test_status_table_counts_only_confirmed_boxes(project) -> None:
    """Nothing is settled at birth that the founder had any part in."""
    session = _session(FakeRoute(), project, Reader([]), Printer())
    table = status_table(session.state)
    assert "0 of 7 boxes complete" in table
