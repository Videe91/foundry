"""Packet: T-013 — how long a role may take.

One job: hold each role's deadline and retry policy, and recognise a timeout
whoever raised it.

Split from brains.py under the R-017 precedent when the timeout machinery pushed
it past the 300-line ceiling. Per R-026 the split inherits its parent's map
entries.

Version: 0.1.0
"""

from __future__ import annotations

from typing import Any


# Timeout class per role, in seconds, with how many automatic retries.
#
# A retry is only safe because a turn is IDEMPOTENT: run_turn persists nothing
# until the whole turn completes, so a stalled attempt leaves no trace and a
# second attempt starts from the same state.
#
# The researcher gets no retry on purpose. It searches up to eight times, and a
# silent second attempt would double a deliberately expensive operation without
# anyone choosing to spend it. It surfaces immediately instead.
#
# R-030 sweep, 2026-08-19: these are the ONLY three live-call sites in the CLI.
# A future role declares its own class here or inherits the interviewer's.
TIMEOUTS: dict[str, tuple[float, int]] = {
    "interviewer": (120.0, 1),
    "scribe": (60.0, 1),
    "researcher": (300.0, 0),
}


DEFAULT_TIMEOUT_CLASS = "interviewer"


# litellm's own default is 6000s — 100 minutes, which is not a timeout so much
# as a hang with paperwork (T-013).
LITELLM_DEFAULT_TIMEOUT = 6000.0


class BrainTimeout(RuntimeError):
    """A role took too long. Names the role, the wait, and that nothing is lost."""


def timeout_class(role: str) -> tuple[float, int]:
    """This role's (seconds, retries). Unknown roles inherit the interviewer's."""
    return TIMEOUTS.get(role, TIMEOUTS[DEFAULT_TIMEOUT_CLASS])


def is_timeout(exc: BaseException) -> bool:
    """Duck-typed: litellm raises its own Timeout, httpx another, asyncio a third.

    Matching on the name rather than importing three exception classes keeps
    this honest about what it is — a heuristic over other people's types.
    """
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()


def completion_with_timeout(seconds: float) -> Any:
    """litellm.completion with an explicit deadline.

    Passed as route_call's completion_fn rather than added to its kwargs, so the
    Switchboard needs no change to learn about deadlines.
    """

    def call(**kwargs: Any) -> Any:
        import litellm

        return litellm.completion(**kwargs, timeout=seconds)

    return call
