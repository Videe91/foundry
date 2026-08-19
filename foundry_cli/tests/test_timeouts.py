"""Packet: T-013 — timeouts and progress.

One job: prove a stalled call is given up on, that the retry happens only where
a retry is safe and cheap, and that the founder is never left staring at
silence.

The live symptom: a turn hung, and nothing on screen distinguished "the model is
searching" from "the connection died". Both defects were ours.

Version: 0.1.0
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import SLUG, Printer, fake_registry, scribe_json

from foundry_cli.brains import Brains
from foundry_cli.timeouts import (
    DEFAULT_TIMEOUT_CLASS,
    LITELLM_DEFAULT_TIMEOUT,
    TIMEOUTS,
    BrainTimeout,
    is_timeout,
    timeout_class,
)
from foundry_cli.session import THINKING, THINKING_SEARCH, ProgressLine
from intent.state import Turn

TRANSCRIPT = [Turn(role="user", content="I want a tool")]


class Stalling:
    """Times out for the first N calls, then answers.

    R-019: the failure is raised the way litellm raises it — a distinct
    exception type whose name carries "Timeout" — not a sentinel we invented.
    """

    class Timeout(Exception):
        pass

    def __init__(self, stalls: int, reply: str = "next question?") -> None:
        self.stalls = stalls
        self.reply = reply
        self.attempts = 0

    def __call__(self, request, registry, completion_fn=None, cost_fn=None,
                 meter=None, on_chunk=None, stream=True) -> Any:
        self.attempts += 1
        if self.attempts <= self.stalls:
            raise self.Timeout("request timed out")
        from types import SimpleNamespace

        if on_chunk is not None:
            on_chunk(self.reply)
        return SimpleNamespace(
            status="ok", content=self.reply, model_used="fake/model",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2,
                                  total_tokens=12, cost_usd=0.001,
                                  cached_tokens=0, cache_creation_tokens=0),
        )


def _brains(route: Any, **kwargs: Any) -> Brains:
    return Brains(slug=SLUG, registry=fake_registry(), route=route, **kwargs)


# --- the classes ------------------------------------------------------------


def test_every_live_call_site_has_a_declared_class() -> None:
    """R-030 sweep: three roles make live calls today, and all three are here."""
    assert set(TIMEOUTS) == {"interviewer", "scribe", "researcher"}


def test_a_future_role_inherits_the_interviewers_class() -> None:
    """Nobody has to remember to add a row before a new role can be called."""
    assert timeout_class("a_new_role") == TIMEOUTS[DEFAULT_TIMEOUT_CLASS]


def test_the_researcher_is_the_patient_one_and_the_scribe_the_impatient() -> None:
    """Structure, not exact seconds: the ORDER is the design (the researcher
    searches eight times; the scribe extracts from text it already has)."""
    scribe_seconds, _ = timeout_class("scribe")
    interviewer_seconds, _ = timeout_class("interviewer")
    researcher_seconds, _ = timeout_class("researcher")
    assert scribe_seconds < interviewer_seconds < researcher_seconds


def test_every_class_is_far_below_litellms_default() -> None:
    """litellm's 6000s is not a timeout, it is a hang with paperwork."""
    for seconds, _retries in TIMEOUTS.values():
        assert seconds < LITELLM_DEFAULT_TIMEOUT / 10


def test_only_the_expensive_role_refuses_to_retry() -> None:
    """A silent second sweep would double a deliberately expensive operation
    without anyone choosing to spend it."""
    assert timeout_class("researcher")[1] == 0
    assert timeout_class("interviewer")[1] >= 1
    assert timeout_class("scribe")[1] >= 1


@pytest.mark.parametrize("name", ["Timeout", "ReadTimeout", "APITimeoutError"])
def test_timeouts_are_recognised_by_name_across_libraries(name: str) -> None:
    exc = type(name, (Exception,), {})()
    assert is_timeout(exc)


def test_an_ordinary_failure_is_not_mistaken_for_a_timeout() -> None:
    """Discriminating: retrying a real error would hide it behind a duplicate."""
    assert is_timeout(ValueError("bad request")) is False
    assert is_timeout(RuntimeError("overloaded")) is False


# --- retry where it is safe -------------------------------------------------


def test_the_interviewer_retries_once_and_recovers() -> None:
    """Safe because a turn is idempotent — run_turn persists nothing until the
    whole turn completes, so a stalled attempt leaves no trace."""
    route = Stalling(stalls=1)
    reply = _brains(route).interviewer(TRANSCRIPT, {}, {})
    assert reply == "next question?"
    assert route.attempts == 2


def test_the_scribe_retries_once_and_recovers() -> None:
    route = Stalling(stalls=1, reply=scribe_json())
    update = _brains(route).scribe(TRANSCRIPT, {})
    assert update.boxes == {}
    assert route.attempts == 2


def test_a_second_stall_gives_up_naming_the_role_and_the_wait() -> None:
    route = Stalling(stalls=2)
    with pytest.raises(BrainTimeout) as excinfo:
        _brains(route).interviewer(TRANSCRIPT, {}, {})
    message = str(excinfo.value)
    assert "interviewer" in message
    assert "s and was given up on" in message
    assert route.attempts == 2


def test_the_message_says_nothing_is_lost_and_how_to_resume() -> None:
    """A founder who has answered eight questions needs to know that."""
    route = Stalling(stalls=2)
    with pytest.raises(BrainTimeout) as excinfo:
        _brains(route).interviewer(TRANSCRIPT, {}, {})
    message = str(excinfo.value)
    assert "Nothing is lost" in message
    assert f"foundry_cli intent {SLUG}" in message


def test_the_researcher_does_not_retry(tmp_path) -> None:
    route = Stalling(stalls=1)
    with pytest.raises(BrainTimeout) as excinfo:
        _brains(route).researcher({"goal": {}})
    assert "researcher" in str(excinfo.value)
    assert route.attempts == 1, "the expensive role must surface immediately"


def test_a_non_timeout_error_is_not_retried() -> None:
    class Broken:
        def __init__(self) -> None:
            self.attempts = 0

        def __call__(self, *_a: Any, **_k: Any) -> Any:
            self.attempts += 1
            raise ValueError("malformed request")

    route = Broken()
    with pytest.raises(ValueError):
        _brains(route).interviewer(TRANSCRIPT, {}, {})
    assert route.attempts == 1


# --- the progress line ------------------------------------------------------


def test_the_line_goes_up_before_the_call_and_comes_down_after() -> None:
    printer = Printer()
    progress = ProgressLine(printer)
    brains = _brains(Stalling(stalls=0, reply=scribe_json()),
                     on_waiting=progress.begin, on_ready=progress.end)
    brains.scribe(TRANSCRIPT, {})

    text = printer.text
    assert THINKING in text
    assert "\r" in text, "the line was never cleared"


def test_a_searching_role_says_so() -> None:
    """"[thinking…]" for 30 seconds is worrying; "may be searching" is not."""
    printer = Printer()
    progress = ProgressLine(printer)
    progress.begin("interviewer", searching=True)
    assert THINKING_SEARCH in printer.text
    assert "searching" in printer.text


def test_clearing_twice_is_harmless() -> None:
    """The first delta clears it; the call's return would clear it again."""
    printer = Printer()
    progress = ProgressLine(printer)
    progress.begin("interviewer", searching=False)
    progress.end()
    before = printer.text
    progress.end()
    assert printer.text == before


def test_the_first_delta_clears_the_line_before_the_reply_prints() -> None:
    """Order matters: a reply printed under a stale marker reads as garbage."""
    printer = Printer()
    progress = ProgressLine(printer)
    deltas: list[str] = []
    brains = _brains(Stalling(stalls=0), on_delta=deltas.append,
                     on_waiting=progress.begin, on_ready=progress.end)
    brains.interviewer(TRANSCRIPT, {}, {})

    text = printer.text
    assert text.index(THINKING) < text.index("\r")
    assert deltas == ["next question?"]


def test_no_progress_callbacks_means_no_output_at_all() -> None:
    """Discriminating: the engine-facing Brains must stay printable-free, so
    every offline test does not suddenly grow terminal noise."""
    printer = Printer()
    _brains(Stalling(stalls=0, reply=scribe_json())).scribe(TRANSCRIPT, {})
    assert printer.text == ""
